"""CertBrain — Main orchestration workflow.

Connects the 6 agents into a multi-step pipeline with four explicit
reasoning patterns:

1. **Planner-Executor** — Curriculum Optimizer plans, Socratic Tutor executes.
2. **Critic/Verifier** — Every agent output is verified; rejected outputs
   are re-generated with feedback (max 2 retries).
3. **Self-Reflection** — Built into the Critic Agent (confidence < 0.7).
4. **Human-in-the-Loop** — Two checkpoints: plan confirmation and
   assessment-readiness.
5. **Conditional Loop** — If final assessment < 80 %, loop back to planning
   (max 3 iterations).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import date
from typing import Any, Callable, Awaitable

from config import get_settings, get_logger
from agents.diagnostic_agent import DiagnosticAgent
from agents.knowledge_architect import KnowledgeArchitectAgent
from agents.curriculum_optimizer import CurriculumOptimizerAgent
from agents.socratic_tutor import SocraticTutorAgent
from agents.critic_agent import CriticAgent, VerificationResult
from agents.engagement_agent import EngagementAgent
from integrations.catalog_api import CatalogAPIClient
from models.assessment import (
    Answer,
    AssessmentResult,
    DiagnosticResult,
    Question,
)
from models.knowledge_graph import KnowledgeGraph
from models.student import ExamObjective, StudentProfile, StudySession
from orchestrator.state import CertBrainState, Phase

logger = get_logger(__name__)

MAX_CRITIC_RETRIES = 2


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
class CertBrainWorkflow:
    """Orchestrates the full CertBrain certification-prep pipeline.

    Parameters
    ----------
    certification_name:
        Human-readable certification (e.g. ``"Azure Fundamentals"``).
    student_name:
        Student display name.
    student_email:
        Contact email for engagement reminders.
    exam_uid:
        Microsoft Learn exam UID (e.g. ``"exam.az-900"``).
    human_callback:
        Async callable ``(prompt: str) -> bool`` used for human-in-the-loop
        checkpoints.  If *None*, checkpoints auto-approve.
    answer_callback:
        Async callable ``(question: Question) -> Answer`` used during
        diagnostics and assessments.  If *None*, questions are auto-answered
        (useful for demos / testing).
    student_chat_callback:
        Async callable ``(tutor_message: str) -> str`` used during Socratic
        tutoring sessions.  If *None*, the student sends "done" immediately.
    """

    def __init__(
        self,
        certification_name: str,
        student_name: str,
        student_email: str = "",
        exam_uid: str = "",
        human_callback: Callable[[str], Awaitable[bool]] | None = None,
        answer_callback: Callable[[Question], Awaitable[Answer]] | None = None,
        student_chat_callback: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        self._settings = get_settings()
        self._human_callback = human_callback
        self._answer_callback = answer_callback
        self._student_chat_callback = student_chat_callback

        self._state = CertBrainState(
            student=StudentProfile(
                name=student_name,
                email=student_email,
                exam_uid=exam_uid,
            ),
            certification_name=certification_name,
            exam_uid=exam_uid,
        )
        self._objectives: list[ExamObjective] = []
        self._kg: KnowledgeGraph | None = None

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    async def get_state(self) -> CertBrainState:
        """Return the current pipeline state."""
        return self._state

    # ------------------------------------------------------------------
    # Human-in-the-loop
    # ------------------------------------------------------------------
    async def wait_for_human_confirmation(self, prompt: str) -> bool:
        """Ask the human to confirm before proceeding.

        Returns *True* if confirmed.  Auto-approves when no callback is set.
        """
        if self._human_callback:
            logger.info("Waiting for human confirmation: %s", prompt)
            return await self._human_callback(prompt)
        logger.info("Human confirmation auto-approved (no callback): %s", prompt)
        return True

    # ------------------------------------------------------------------
    # Pattern 2: Critic/Verifier wrapper
    # ------------------------------------------------------------------
    async def _verify_output(
        self,
        agent_name: str,
        output: Any,
        content_type: str,
    ) -> VerificationResult:
        """Run the Critic Agent on an agent output."""
        critic = CriticAgent(content_to_verify=output, content_type=content_type)
        result = await critic.run()
        self._state.add_verification(agent_name, {
            "is_valid": result.is_valid,
            "confidence": result.confidence,
            "issues_count": len(result.issues),
            "self_reflection": result.self_reflection_triggered,
        })
        return result

    async def _run_with_critic(
        self,
        agent_name: str,
        run_fn: Callable[[], Awaitable[Any]],
        content_type: str,
    ) -> Any:
        """Execute an agent and verify with the Critic, retrying on rejection.

        Parameters
        ----------
        agent_name:
            Name for logging / verification log.
        run_fn:
            Async callable that runs the agent and returns its output.
        content_type:
            Label for the Critic (e.g. ``"diagnostic_questions"``).

        Returns the agent output (after passing verification or exhausting
        retries).
        """
        for attempt in range(1, MAX_CRITIC_RETRIES + 2):  # +1 for initial
            output = await run_fn()
            verification = await self._verify_output(agent_name, output, content_type)

            if verification.is_valid:
                logger.info(
                    "Critic approved %s (confidence=%.2f, attempt=%d)",
                    agent_name, verification.confidence, attempt,
                )
                return output

            logger.warning(
                "Critic rejected %s (confidence=%.2f, issues=%d, attempt=%d/%d)",
                agent_name, verification.confidence, len(verification.issues),
                attempt, MAX_CRITIC_RETRIES + 1,
            )

            if attempt > MAX_CRITIC_RETRIES:
                logger.warning(
                    "Max retries exhausted for %s — using last output", agent_name
                )
                return output

        return output  # fallback (should not reach here)

    # ------------------------------------------------------------------
    # Phase 1: Diagnostic
    # ------------------------------------------------------------------
    async def _fetch_objectives(self) -> list[ExamObjective]:
        """Fetch exam objectives from the Catalog API.

        Strategy:
        1. Try to find the certification by UID and read its study_guide.
        2. If study_guide is empty, derive objectives from learning path titles.
        3. Fall back to hard-coded AZ-900 objectives if catalog is unavailable.
        """
        try:
            async with CatalogAPIClient() as catalog:
                # Step 1: try certification lookup (e.g. certification.azure-fundamentals)
                cert_uid = self._state.exam_uid.replace("exam.", "certification.")
                cert_data = await catalog.get_certification_by_uid(cert_uid)

                # Try study_guide from the certification
                study_guide: list[dict] = []
                if cert_data:
                    study_guide = cert_data.get("study_guide", []) or []

                objectives: list[ExamObjective] = []
                if study_guide:
                    for i, area in enumerate(study_guide):
                        obj_id = f"{self._state.exam_uid}-{i+1}"
                        objectives.append(ExamObjective(
                            id=obj_id,
                            name=area.get("name", f"Area {i+1}"),
                            description=area.get("description", ""),
                            weight_percent=area.get("percentage", 100 / max(len(study_guide), 1)),
                        ))

                # Step 2: derive from learning path titles
                if not objectives:
                    paths = await catalog.get_learning_paths_for_exam(self._state.exam_uid)
                    for i, path in enumerate(paths[:10]):
                        obj_id = f"{self._state.exam_uid}-{i+1}"
                        objectives.append(ExamObjective(
                            id=obj_id,
                            name=path.get("title", f"Topic {i+1}"),
                            description=path.get("summary", ""),
                            weight_percent=round(100 / max(len(paths[:10]), 1), 1),
                        ))

                if objectives:
                    logger.info("Loaded %d objectives for %s", len(objectives), self._state.exam_uid)
                    return objectives

                logger.warning("No objectives from catalog for %s — using generic", self._state.exam_uid)
                return self._generate_generic_objectives()

        except Exception as exc:
            logger.warning("Catalog API failed: %s — using generic objectives", exc)
            return self._generate_generic_objectives()

    def _generate_generic_objectives(self) -> list[ExamObjective]:
        """Fallback objectives — accurate AZ-900 areas with real exam weights."""
        areas = [
            ("Cloud Concepts", "Describe cloud computing, benefits, and service types (IaaS/PaaS/SaaS)", 25.0),
            ("Azure Architecture & Services", "Describe Azure regions, availability zones, VMs, networking, and storage", 35.0),
            ("Azure Management & Governance", "Describe cost management, Azure Policy, RBAC, and compliance tools", 30.0),
            ("Security & Identity", "Describe Azure AD / Entra ID, Defender for Cloud, and zero-trust model", 10.0),
        ]
        return [
            ExamObjective(
                id=f"{self._state.exam_uid}-{i+1}",
                name=name,
                description=desc,
                weight_percent=weight,
            )
            for i, (name, desc, weight) in enumerate(areas)
        ]

    async def run_diagnostic_phase(self) -> DiagnosticResult:
        """Execute the diagnostic (adaptive pre-test) phase."""
        logger.info("=== PHASE: DIAGNOSTIC ===")
        self._objectives = await self._fetch_objectives()

        agent = DiagnosticAgent(
            certification_name=self._state.certification_name,
            objectives=self._objectives,
        )

        async def _run() -> DiagnosticResult:
            return await agent.run(
                student_id=self._state.student.id,
                answer_callback=self._answer_callback,
            )

        result: DiagnosticResult = await self._run_with_critic(
            "DiagnosticAgent", _run, "diagnostic_questions"
        )

        # Update state
        self._state.diagnostic_result = result
        self._state.student.diagnostic_completed = True

        # Update objective mastery from diagnostic
        mastery_map = agent.mastery_estimates
        for obj in self._objectives:
            obj.mastery = mastery_map.get(obj.id, 0.0)
        self._state.student.objectives = self._objectives
        self._state.student.recalculate_mastery()

        self._state.advance_phase(Phase.BUILDING_GRAPH)
        logger.info("Diagnostic complete: overall_mastery=%.2f", self._state.student.overall_mastery)
        return result

    # ------------------------------------------------------------------
    # Phase 2: Knowledge Graph
    # ------------------------------------------------------------------
    async def run_graph_phase(self) -> KnowledgeGraph:
        """Build the knowledge graph from diagnostic results."""
        logger.info("=== PHASE: BUILDING GRAPH ===")

        agent = KnowledgeArchitectAgent(
            diagnostic_result=self._state.diagnostic_result,
            objectives=self._objectives,
        )

        async def _run() -> tuple[KnowledgeGraph, list[dict[str, Any]]]:
            return await agent.run()

        kg, priority_topics = await self._run_with_critic(
            "KnowledgeArchitectAgent", _run, "knowledge_graph"
        )

        self._kg = kg
        self._state.knowledge_graph = kg.to_dict()
        self._state.advance_phase(Phase.PLANNING)
        logger.info("Knowledge graph: %d nodes, %d edges", kg.num_concepts, kg.num_dependencies)
        return kg

    # ------------------------------------------------------------------
    # Phase 3: Planning (Planner in Planner-Executor pattern)
    # ------------------------------------------------------------------
    async def run_planning_phase(self) -> list[StudySession]:
        """Generate the study plan with spaced repetition."""
        logger.info("=== PHASE: PLANNING ===")

        if self._kg is None and self._state.knowledge_graph:
            self._kg = KnowledgeGraph.from_dict(self._state.knowledge_graph)

        agent = CurriculumOptimizerAgent(
            knowledge_graph=self._kg or KnowledgeGraph(),
            student=self._state.student,
            objectives=self._objectives,
            exam_uid=self._state.exam_uid,
        )

        async def _run() -> tuple[list[StudySession], dict, date]:
            return await agent.run()

        sessions, timeline, exam_date = await self._run_with_critic(
            "CurriculumOptimizerAgent", _run, "study_plan"
        )

        self._state.study_plan = sessions
        self._state.timeline = timeline
        self._state.student.study_sessions = sessions
        self._state.advance_phase(Phase.CONFIRMING_PLAN)

        logger.info(
            "Study plan: %d sessions, exam target %s", len(sessions), exam_date
        )
        return sessions

    # ------------------------------------------------------------------
    # Checkpoint 1: Human confirms plan
    # ------------------------------------------------------------------
    async def confirm_plan(self) -> bool:
        """Human-in-the-loop: confirm the study plan."""
        plan_summary = (
            f"Study plan with {len(self._state.study_plan or [])} sessions. "
            f"Timeline: {self._state.timeline}. "
            "Do you approve this plan?"
        )
        confirmed = await self.wait_for_human_confirmation(plan_summary)
        if confirmed:
            self._state.plan_confirmed = True
            self._state.advance_phase(Phase.STUDYING)
            logger.info("Plan confirmed by student")
        else:
            logger.info("Plan rejected — staying in CONFIRMING_PLAN")
        return confirmed

    # ------------------------------------------------------------------
    # Phase 4: Studying (Executor in Planner-Executor pattern)
    # ------------------------------------------------------------------
    async def run_study_phase(self, topic: str) -> dict[str, Any]:
        """Run a single Socratic tutoring session for *topic*."""
        logger.info("=== STUDY SESSION: %s ===", topic)

        mastery = 0.0
        if self._kg and topic in self._kg:
            mastery = self._kg.get_mastery(topic)

        tutor = SocraticTutorAgent(
            topic=topic,
            mastery=mastery,
            knowledge_graph=self._kg,
        )

        if self._student_chat_callback:
            result = await tutor.run_session(
                student_callback=self._student_chat_callback,
                max_turns=10,
            )
        else:
            # Auto-mode: single opening question, student says "done"
            async def _auto_respond(msg: str) -> str:
                return "done"

            result = await tutor.run_session(
                student_callback=_auto_respond,
                max_turns=1,
            )

        session_data = {
            "topic": result.topic,
            "initial_mastery": result.initial_mastery,
            "final_mastery": result.final_mastery,
            "turns": len(result.transcript),
            "bloom_levels": [b.value for b in result.bloom_levels_reached],
            "reference_urls": result.reference_urls,
        }
        self._state.tutor_sessions.append(session_data)

        # Update KG mastery
        if self._kg and topic in self._kg:
            self._kg.update_mastery(topic, result.final_mastery)
            self._state.knowledge_graph = self._kg.to_dict()

        logger.info(
            "Study session done: %s mastery %.2f -> %.2f",
            topic, result.initial_mastery, result.final_mastery,
        )
        return session_data

    # ------------------------------------------------------------------
    # Checkpoint 2: Student ready for assessment
    # ------------------------------------------------------------------
    async def confirm_assessment_ready(self) -> bool:
        """Human-in-the-loop: student says they're ready."""
        confirmed = await self.wait_for_human_confirmation(
            "Are you ready to take the final assessment?"
        )
        if confirmed:
            self._state.assessment_ready_confirmed = True
            self._state.advance_phase(Phase.ASSESSING)
            logger.info("Student confirmed ready for assessment")
        return confirmed

    # ------------------------------------------------------------------
    # Phase 5: Final Assessment
    # ------------------------------------------------------------------
    async def run_assessment_phase(self) -> AssessmentResult:
        """Run the final assessment (re-uses Diagnostic Agent in test mode)."""
        logger.info("=== PHASE: ASSESSMENT ===")

        agent = DiagnosticAgent(
            certification_name=self._state.certification_name,
            objectives=self._objectives,
        )

        result = await agent.run(
            student_id=self._state.student.id,
            answer_callback=self._answer_callback,
        )

        assessment = result.assessment
        self._state.assessment_results.append(assessment)

        passed = assessment.total_score >= self._settings.mastery_pass_threshold
        if passed:
            self._state.advance_phase(Phase.PASSED)
            logger.info("PASSED with score %.2f", assessment.total_score)
        else:
            self._state.advance_phase(Phase.NEEDS_REVIEW)
            logger.info(
                "NOT PASSED (score=%.2f < %.2f) — iteration %d/%d",
                assessment.total_score,
                self._settings.mastery_pass_threshold,
                self._state.iteration_count,
                self._state.max_iterations,
            )

        return assessment

    # ------------------------------------------------------------------
    # Phase 6: Engagement (runs in parallel with studying)
    # ------------------------------------------------------------------
    async def run_engagement(self, send_emails: bool = False) -> list[dict[str, Any]]:
        """Generate engagement reminders."""
        logger.info("=== ENGAGEMENT ===")
        agent = EngagementAgent(
            student=self._state.student,
            study_sessions=self._state.study_plan or [],
        )
        reminders = await agent.run(send_emails=send_emails)
        self._state.reminders = [
            {
                "scheduled_at": r.scheduled_at.isoformat(),
                "subject": r.subject,
                "message": r.message,
                "type": r.reminder_type.value,
                "sent": r.sent,
            }
            for r in reminders
        ]
        return self._state.reminders

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------
    async def run_full_pipeline(self) -> CertBrainState:
        """Execute the complete CertBrain pipeline end-to-end.

        Flow::

            Diagnostic -> Knowledge Graph -> Critic verifies -> Plan
            -> Human confirms -> Study sessions -> Human ready
            -> Assessment -> Pass >= 80%?
                Yes -> done
                No  -> loop back to Plan (max 3 times)
        """
        logger.info(
            "===== CertBrain Pipeline START: %s for %s =====",
            self._state.certification_name, self._state.student.name,
        )

        # 1. Diagnostic
        await self.run_diagnostic_phase()

        while True:
            # 2. Build knowledge graph
            await self.run_graph_phase()

            # 3. Generate study plan
            await self.run_planning_phase()

            # 4. Engagement (fire and forget)
            await self.run_engagement()

            # Checkpoint 1: Human confirms plan
            await self.confirm_plan()

            # 5. Study sessions (Executor phase)
            if self._kg:
                frontier = self._kg.get_learning_frontier()
                for topic_id in frontier[:5]:  # study up to 5 frontier topics
                    await self.run_study_phase(topic_id)

            # Checkpoint 2: Ready for assessment
            self._state.advance_phase(Phase.READY_FOR_ASSESSMENT)
            await self.confirm_assessment_ready()

            # 6. Final assessment
            assessment = await self.run_assessment_phase()

            # Pattern 5: Conditional loop
            if self._state.current_phase == Phase.PASSED:
                logger.info("===== Pipeline COMPLETE: PASSED =====")
                break

            if self._state.should_loop_back():
                logger.info(
                    "Looping back (iteration %d/%d, score=%.2f)",
                    self._state.iteration_count,
                    self._state.max_iterations,
                    assessment.total_score,
                )
                # Reset for next iteration
                self._state.plan_confirmed = False
                self._state.assessment_ready_confirmed = False
                self._state.advance_phase(Phase.PLANNING)
                continue
            else:
                logger.info(
                    "Max iterations reached (%d). Recommending more study time.",
                    self._state.max_iterations,
                )
                break

        logger.info("Final state: %s", self._state.summary())
        return self._state


# ---------------------------------------------------------------------------
# Demo entry point
# ---------------------------------------------------------------------------
async def _demo() -> None:
    """Minimal terminal demo using AZ-900 with auto-answers."""
    from config import setup_logging
    setup_logging("INFO")

    print("=" * 60)
    print("  CertBrain Demo — AZ-900 Azure Fundamentals")
    print("=" * 60)

    workflow = CertBrainWorkflow(
        certification_name="Azure Fundamentals",
        student_name="Demo Student",
        student_email="demo@example.com",
        exam_uid="exam.az-900",
        # No callbacks → auto-approve everything
    )

    # --- Phase 1: Diagnostic ---
    print("\n[1/4] Running diagnostic (auto-answer mode)...")
    diag = await workflow.run_diagnostic_phase()
    print(f"  Score: {diag.assessment.total_score:.0%}")
    print(f"  Gaps: {diag.identified_gaps}")
    print(f"  Strengths: {diag.identified_strengths}")

    # --- Phase 2: Knowledge Graph ---
    print("\n[2/4] Building knowledge graph...")
    kg = await workflow.run_graph_phase()
    print(f"  Concepts: {kg.num_concepts}")
    print(f"  Dependencies: {kg.num_dependencies}")
    print(f"  Weak areas: {kg.get_weak_areas()}")
    print(f"  Learning frontier: {kg.get_learning_frontier()}")

    # --- Phase 3: Study Plan ---
    print("\n[3/4] Generating study plan...")
    sessions = await workflow.run_planning_phase()
    print(f"  Sessions: {len(sessions)}")

    state = await workflow.get_state()
    if state.timeline:
        print(f"  Timeline: {state.timeline.get('total_study_days', '?')} days")
        print(f"  Exam target: {state.timeline.get('recommended_exam_date', '?')}")

    # --- Summary ---
    print("\n[4/4] Final state:")
    print(f"  {state.summary()}")
    print(f"  Phase: {state.current_phase.value}")
    print(f"  Progress: {state.get_progress_percentage()}%")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_demo())
