"""CertBrain — Curriculum Optimizer Agent (SM-2 Spaced Repetition).

Creates a personalised study plan that:
- Respects prerequisite ordering from the KnowledgeGraph.
- Maps each topic to real Microsoft Learn modules via the Catalog API.
- Schedules review sessions using the SM-2 spaced repetition algorithm.
- Generates weekly milestones and a recommended exam date.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from config import get_settings, get_logger
from integrations.azure_ai import AzureAIClient
from integrations.catalog_api import CatalogAPIClient
from models.knowledge_graph import KnowledgeGraph
from models.student import (
    BloomLevel,
    ExamObjective,
    SessionStatus,
    StudentProfile,
    StudySession,
)

logger = get_logger(__name__)

SYSTEM_PROMPT = """\
You are a Curriculum Optimizer for Microsoft certification exam preparation.

## Your role
Given a knowledge graph (concepts with mastery levels and dependencies) and \
a list of available Microsoft Learn modules, create an optimal study plan that:
1. Respects prerequisite order — foundational topics first.
2. Prioritises weak areas (low mastery) but also schedules reviews for strong areas.
3. Allocates realistic daily study time (30-90 min per session).
4. Includes spaced repetition reviews at increasing intervals.
5. Sets weekly milestones with target mastery thresholds.

## Output format — strict JSON, no markdown fences
{
  "sessions": [
    {
      "objective_id": "<id>",
      "module_uid": "<microsoft learn module uid>",
      "duration_minutes": 45,
      "bloom_target": "apply",
      "day_offset": 0
    }
  ],
  "milestones": [
    {"week": 1, "target_mastery": 0.5, "topics": ["id1", "id2"]}
  ],
  "total_days": 28,
  "rationale": "<brief explanation of strategy>"
}

## Rules
- day_offset is relative to study start (0 = first day).
- Keep sessions under 90 minutes for focus.
- Schedule at least 1 rest day per week.
- Bloom target should escalate: REMEMBER → UNDERSTAND → APPLY → ANALYZE.
"""


# ---------------------------------------------------------------------------
# SM-2 Algorithm
# ---------------------------------------------------------------------------
def sm2_next_review(
    quality: int,
    repetition: int,
    easiness: float,
    interval: int,
) -> tuple[int, float, int]:
    """Compute next SM-2 interval.

    Parameters
    ----------
    quality: 0-5 self-assessment score (0=blackout, 5=perfect).
    repetition: current repetition number.
    easiness: current easiness factor (>= 1.3).
    interval: current interval in days.

    Returns
    -------
    tuple[int, float, int]
        (new_interval, new_easiness, new_repetition)
    """
    if quality >= 3:
        if repetition == 0:
            new_interval = 1
        elif repetition == 1:
            new_interval = 6
        else:
            new_interval = round(interval * easiness)
        new_repetition = repetition + 1
    else:
        new_interval = 1
        new_repetition = 0

    new_easiness = easiness + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_easiness = max(1.3, new_easiness)

    return new_interval, new_easiness, new_repetition


# ---------------------------------------------------------------------------
# Curriculum Optimizer Agent
# ---------------------------------------------------------------------------
class CurriculumOptimizerAgent:
    """Creates a spaced-repetition study plan mapped to MS Learn modules.

    Parameters
    ----------
    knowledge_graph:
        Populated graph from the Knowledge Architect.
    student:
        Current student profile.
    objectives:
        Exam objectives.
    exam_uid:
        Exam identifier for module lookup (e.g. ``"exam.az-900"``).
    """

    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        student: StudentProfile,
        objectives: list[ExamObjective],
        exam_uid: str = "",
    ) -> None:
        self._kg = knowledge_graph
        self._student = student
        self._objectives = objectives
        self._exam_uid = exam_uid or student.exam_uid
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Module mapping
    # ------------------------------------------------------------------
    async def _fetch_modules(self) -> dict[str, dict[str, Any]]:
        """Fetch MS Learn modules for the exam and build a lookup by UID."""
        module_map: dict[str, dict[str, Any]] = {}
        try:
            async with CatalogAPIClient() as catalog:
                modules = await catalog.get_modules_for_exam(self._exam_uid)
                for m in modules:
                    module_map[m.get("uid", "")] = m
                logger.info("Fetched %d modules for %s", len(module_map), self._exam_uid)
        except Exception as exc:
            logger.warning("Failed to fetch modules: %s", exc)
        return module_map

    # ------------------------------------------------------------------
    # LLM plan generation
    # ------------------------------------------------------------------
    async def _generate_plan_with_llm(
        self,
        azure_client: AzureAIClient,
        module_uids: list[str],
        module_map: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Ask the LLM to create the study plan structure."""
        topo_order = self._kg.get_topological_order()
        concept_lines: list[str] = []
        for cid in topo_order:
            mastery = self._kg.get_mastery(cid)
            name = self._kg._graph.nodes[cid].get("name", cid) if hasattr(self._kg, "_graph") else cid
            concept_lines.append(f"  {cid} ({name}): mastery={mastery:.0%}")

        # Pass module UIDs AND titles so LLM can assign sensibly
        module_lines: list[str] = []
        for uid in module_uids[:30]:
            title = (module_map or {}).get(uid, {}).get("title", uid) if module_map else uid
            module_lines.append(f"  {uid}: {title}")

        user_msg = (
            f"Student: {self._student.name}\n"
            f"Exam: {self._exam_uid}\n"
            f"Overall mastery: {self._student.overall_mastery:.0%}\n\n"
            "Concepts in prerequisite order:\n"
            + "\n".join(concept_lines)
            + "\n\nAvailable Microsoft Learn modules (uid: title):\n"
            + "\n".join(module_lines)
            + "\n\nCreate a study plan. Assign module_uid from the list above "
            "matching each concept to the most relevant module title. "
            "Use JSON format specified."
        )

        try:
            return await azure_client.chat_completion_json(
                SYSTEM_PROMPT, user_msg, temperature=0.4, max_tokens=2500
            )
        except Exception as exc:
            logger.warning("LLM plan generation failed: %s — using fallback", exc)
            return self._fallback_plan(topo_order)

    def _fallback_plan(self, topo_order: list[str]) -> dict[str, Any]:
        """Generate a simple sequential plan when the LLM is unavailable."""
        sessions = []
        for i, cid in enumerate(topo_order):
            sessions.append({
                "objective_id": cid,
                "module_uid": "",
                "duration_minutes": 45,
                "bloom_target": "understand",
                "day_offset": i,
            })
        return {
            "sessions": sessions,
            "milestones": [
                {"week": 1, "target_mastery": 0.5, "topics": topo_order[:3]},
            ],
            "total_days": len(topo_order) + 7,
            "rationale": "Fallback sequential plan.",
        }

    # ------------------------------------------------------------------
    # Session construction with SM-2
    # ------------------------------------------------------------------
    def _build_sessions(
        self,
        llm_plan: dict[str, Any],
        start_date: date,
        module_map: dict[str, dict[str, Any]] | None = None,
    ) -> list[StudySession]:
        """Convert LLM plan into StudySession objects with SM-2 scheduling."""
        sessions: list[StudySession] = []
        for item in llm_plan.get("sessions", []):
            obj_id = item.get("objective_id", "")
            day_off = item.get("day_offset", 0)
            bloom_str = item.get("bloom_target", "understand")
            module_uid = item.get("module_uid", "")

            # Resolve real module title from catalog data
            mod_info = (module_map or {}).get(module_uid, {})
            module_title = mod_info.get("title", "") or mod_info.get("summary", "")

            try:
                bloom = BloomLevel(bloom_str)
            except ValueError:
                bloom = BloomLevel.UNDERSTAND

            # Initial session
            mastery = self._kg.get_mastery(obj_id) if obj_id in self._kg else 0.0
            quality = int(mastery * 5)  # map mastery 0-1 to SM-2 quality 0-5
            interval, easiness, rep = sm2_next_review(
                quality=quality, repetition=0, easiness=2.5, interval=1,
            )

            sched_date = start_date + timedelta(days=day_off)
            session = StudySession(
                objective_id=obj_id,
                module_uid=module_uid,
                scheduled_date=sched_date,
                duration_minutes=item.get("duration_minutes", 45),
                bloom_target=bloom,
                easiness_factor=easiness,
                interval_days=interval,
                repetition_number=rep,
                next_review_date=sched_date + timedelta(days=interval),
                notes=module_title,  # store real title in notes for UI
            )
            sessions.append(session)

            # Schedule one review session
            review_date = sched_date + timedelta(days=interval)
            next_interval, next_ease, next_rep = sm2_next_review(
                quality=quality, repetition=rep, easiness=easiness, interval=interval,
            )
            review = StudySession(
                objective_id=obj_id,
                module_uid=module_uid,
                scheduled_date=review_date,
                duration_minutes=max(20, item.get("duration_minutes", 45) // 2),
                bloom_target=bloom,
                easiness_factor=next_ease,
                interval_days=next_interval,
                repetition_number=next_rep,
                next_review_date=review_date + timedelta(days=next_interval),
                notes=f"Review: {module_title}" if module_title else "Spaced repetition review",
            )
            sessions.append(review)

        # Sort by date
        sessions.sort(key=lambda s: s.scheduled_date)
        return sessions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run(
        self,
        start_date: date | None = None,
    ) -> tuple[list[StudySession], dict[str, Any], date]:
        """Generate the complete study plan.

        Parameters
        ----------
        start_date:
            When the student begins studying. Defaults to today.

        Returns
        -------
        tuple[list[StudySession], dict, date]
            (sessions, timeline_with_milestones, recommended_exam_date)
        """
        start = start_date or date.today()
        logger.info("Curriculum Optimizer starting from %s", start)

        # Fetch MS Learn modules
        module_map = await self._fetch_modules()
        module_uids = list(module_map.keys())

        # Generate plan with LLM (pass full module_map so titles are included)
        azure_client = AzureAIClient()
        try:
            llm_plan = await self._generate_plan_with_llm(azure_client, module_uids, module_map)
        finally:
            await azure_client.close()

        # Build sessions with SM-2 (pass module_map for title lookup)
        sessions = self._build_sessions(llm_plan, start, module_map)

        # Timeline
        total_days = llm_plan.get("total_days", 28)
        recommended_exam = start + timedelta(days=total_days + 7)  # +1 week buffer
        timeline: dict[str, Any] = {
            "start_date": start.isoformat(),
            "recommended_exam_date": recommended_exam.isoformat(),
            "total_study_days": total_days,
            "total_sessions": len(sessions),
            "milestones": llm_plan.get("milestones", []),
            "rationale": llm_plan.get("rationale", ""),
        }

        logger.info(
            "Curriculum plan: %d sessions over %d days, exam target %s",
            len(sessions), total_days, recommended_exam,
        )

        return sessions, timeline, recommended_exam
