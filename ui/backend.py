"""CertBrain — Synchronous backend helpers for the Streamlit UI.

Wraps async agent/client calls with asyncio.run() so Streamlit pages
(which run synchronously) can call them directly.

All functions raise on unrecoverable errors so the UI can show st.error().
"""

from __future__ import annotations

import asyncio
import random
import sys
import os
from typing import Any

# Ensure project root is on path when pages call this module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import get_settings, get_logger

logger = get_logger(__name__)

# ── Objectives ────────────────────────────────────────────────────────────────

def fetch_objectives(exam_uid: str = "exam.az-900") -> list[dict[str, Any]]:
    """Fetch real exam objectives from the Catalog API (or fallback).

    Returns a list of dicts with keys: id, name, description, weight_percent.
    """
    async def _run():
        from integrations.catalog_api import CatalogAPIClient
        try:
            async with CatalogAPIClient() as catalog:
                # Try certification lookup
                cert_uid = exam_uid.replace("exam.", "certification.")
                cert = await catalog.get_certification_by_uid(cert_uid)
                study_guide = (cert or {}).get("study_guide", []) or []
                if study_guide:
                    return [
                        {
                            "id": f"{exam_uid}-{i+1}",
                            "name": area.get("name", f"Area {i+1}"),
                            "description": area.get("description", ""),
                            "weight_percent": area.get("percentage", round(100 / max(len(study_guide), 1), 1)),
                        }
                        for i, area in enumerate(study_guide)
                    ]
                # Derive from learning paths
                paths = await catalog.get_learning_paths_for_exam(exam_uid)
                if paths:
                    return [
                        {
                            "id": f"{exam_uid}-{i+1}",
                            "name": p.get("title", f"Topic {i+1}"),
                            "description": p.get("summary", ""),
                            "weight_percent": round(100 / max(len(paths[:8]), 1), 1),
                        }
                        for i, p in enumerate(paths[:8])
                    ]
        except Exception as exc:
            logger.warning("Catalog API failed: %s — using fallback", exc)
        # AZ-900 fallback
        return _az900_objectives(exam_uid)

    return asyncio.run(_run())


def _az900_objectives(exam_uid: str) -> list[dict[str, Any]]:
    """Hard-coded AZ-900 objectives with official exam weights."""
    areas = [
        ("Cloud Concepts", "Describe cloud computing concepts, models, and benefits", 25.0),
        ("Azure Architecture & Services", "Describe Azure core services: compute, networking, storage", 35.0),
        ("Azure Management & Governance", "Describe cost management, Azure Policy, RBAC, and monitoring tools", 30.0),
        ("Security & Identity", "Describe Azure AD / Entra ID, Defender for Cloud, and zero-trust", 10.0),
    ]
    return [
        {"id": f"{exam_uid}-{i+1}", "name": n, "description": d, "weight_percent": w}
        for i, (n, d, w) in enumerate(areas)
    ]


# ── Diagnostic question generation ───────────────────────────────────────────

def generate_question(
    objective: dict[str, Any],
    difficulty: str = "medium",
    cert_name: str = "Azure Fundamentals",
) -> dict[str, Any]:
    """Generate one AI exam question for the given objective.

    Returns a dict with: stem, options (list of {key, text, is_correct}),
    explanation, bloom_level.
    """
    from agents.diagnostic_agent import SYSTEM_PROMPT as DIAG_PROMPT

    async def _run():
        from integrations.azure_ai import AzureAIClient
        user_msg = (
            f"Certification: {cert_name}\n"
            f"Objective ID: {objective['id']}\n"
            f"Objective: {objective['name']}\n"
            f"Description: {objective['description']}\n"
            f"Difficulty: {difficulty}\n\n"
            "Generate ONE question in the JSON format specified."
        )
        client = AzureAIClient()
        try:
            return await client.chat_completion_json(
                DIAG_PROMPT, user_msg, temperature=0.7, max_tokens=800
            )
        finally:
            await client.close()

    try:
        raw = asyncio.run(_run())
        # Shuffle options to eliminate LLM position bias
        opts = raw.get("options", [])
        if opts:
            random.shuffle(opts)
            keys = ["A", "B", "C", "D"]
            opts = [
                {"key": keys[i], "text": o.get("text", ""), "is_correct": o.get("is_correct", False)}
                for i, o in enumerate(opts[:4])
            ]
            raw["options"] = opts
        return raw
    except Exception as exc:
        logger.warning("Question generation failed: %s", exc)
        return {
            "stem": f"What does '{objective['name']}' refer to in Azure?",
            "options": [
                {"key": "A", "text": f"It is related to {objective['name']}", "is_correct": True},
                {"key": "B", "text": "It is not an Azure service", "is_correct": False},
                {"key": "C", "text": "It was deprecated in 2023", "is_correct": False},
                {"key": "D", "text": "None of the above", "is_correct": False},
            ],
            "explanation": "Fallback question — AI unavailable.",
            "bloom_level": "remember",
        }


# ── Knowledge Graph ───────────────────────────────────────────────────────────

def build_knowledge_graph(
    objectives: list[dict[str, Any]],
    mastery_map: dict[str, float],
) -> dict[str, Any]:
    """Build a real knowledge graph from objectives and diagnostic mastery scores.

    Returns a dict with keys: nodes, edges (suitable for brain_viz).
    """
    from models.assessment import DiagnosticResult, AssessmentResult, ObjectiveScore
    from models.student import ExamObjective

    async def _run():
        from integrations.azure_ai import AzureAIClient

        # Build a minimal DiagnosticResult for the KnowledgeArchitectAgent
        obj_scores = [
            ObjectiveScore(objective_id=o["id"], score=mastery_map.get(o["id"], 0.3))
            for o in objectives
        ]
        assessment = AssessmentResult(student_id="ui-student", questions=[], answers=[])
        assessment.objective_scores = obj_scores
        assessment.total_score = sum(s.score for s in obj_scores) / max(len(obj_scores), 1)

        diag = DiagnosticResult(
            student_id="ui-student",
            assessment=assessment,
            identified_gaps=[o["id"] for o in objectives if mastery_map.get(o["id"], 0) < 0.5],
            identified_strengths=[o["id"] for o in objectives if mastery_map.get(o["id"], 0) >= 0.7],
            recommended_start_objectives=[],
            confidence_calibration=0.5,
        )

        exam_objectives = [
            ExamObjective(
                id=o["id"],
                name=o["name"],
                description=o["description"],
                weight_percent=o["weight_percent"],
            )
            for o in objectives
        ]

        from agents.knowledge_architect import KnowledgeArchitectAgent
        agent = KnowledgeArchitectAgent(diagnostic_result=diag, objectives=exam_objectives)
        kg, _ = await agent.run()
        return kg.to_dict()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("KG build failed: %s — returning minimal graph", exc)
        return _fallback_kg(objectives, mastery_map)


def _fallback_kg(
    objectives: list[dict[str, Any]],
    mastery_map: dict[str, float],
) -> dict[str, Any]:
    nodes = [
        {
            "id": o["id"],
            "name": o["name"],
            "mastery": mastery_map.get(o["id"], 0.3),
            "weight_percent": o["weight_percent"],
        }
        for o in objectives
    ]
    edges = [
        {"source": objectives[i]["id"], "target": objectives[i + 1]["id"]}
        for i in range(len(objectives) - 1)
    ]
    return {"nodes": nodes, "edges": edges}


# ── Study Plan ────────────────────────────────────────────────────────────────

def generate_study_plan(
    kg_data: dict[str, Any],
    objectives: list[dict[str, Any]],
    student_name: str,
    exam_uid: str = "exam.az-900",
    overall_mastery: float = 0.35,
) -> dict[str, Any]:
    """Generate a real spaced-repetition study plan.

    Returns a dict matching the DEMO_PLAN shape used in 03_study_plan.py.
    """
    from datetime import date, timedelta

    async def _run():
        from models.knowledge_graph import KnowledgeGraph
        from models.student import ExamObjective, StudentProfile
        from agents.curriculum_optimizer import CurriculumOptimizerAgent
        from integrations.catalog_api import CatalogAPIClient

        # Fetch real module info (title + URL) from Catalog API
        modules_info: dict[str, dict] = {}
        try:
            async with CatalogAPIClient() as catalog:
                mods = await catalog.get_modules_for_exam(exam_uid)
                modules_info = {
                    m.get("uid", ""): {
                        "title": m.get("title", ""),
                        "url": m.get("url", ""),
                    }
                    for m in mods if m.get("uid")
                }
                logger.info("Loaded %d module infos for %s", len(modules_info), exam_uid)
        except Exception as exc:
            logger.warning("Could not fetch module info: %s", exc)

        kg = KnowledgeGraph.from_dict(kg_data)
        student = StudentProfile(
            name=student_name,
            exam_uid=exam_uid,
        )
        student.overall_mastery = overall_mastery

        exam_objectives = [
            ExamObjective(
                id=o["id"],
                name=o["name"],
                description=o["description"],
                weight_percent=o["weight_percent"],
            )
            for o in objectives
        ]

        agent = CurriculumOptimizerAgent(
            knowledge_graph=kg,
            student=student,
            objectives=exam_objectives,
            exam_uid=exam_uid,
        )
        sessions, timeline, exam_date = await agent.run()

        # Convert to UI-compatible format (include real URLs)
        from collections import defaultdict
        weeks: dict[int, list] = defaultdict(list)
        start = date.today()
        for s in sessions:
            day_n = (s.scheduled_date - start).days + 1
            week_n = max(1, (day_n - 1) // 7 + 1)
            module_uid = s.module_uid or ""
            mod_info = modules_info.get(module_uid, {})
            real_url = mod_info.get("url", "")
            # Use real module title, then curriculum note, then objective ID
            module_title = mod_info.get("title", "")
            # s.notes holds module_title from CurriculumOptimizerAgent
            note = s.notes or ""
            is_review = note.startswith("Review:")
            display_topic = module_title or (note.removeprefix("Review: ") if is_review else note) or s.objective_id
            weeks[week_n].append({
                "day": day_n,
                "topic": display_topic,
                "duration": s.duration_minutes,
                "type": "review" if is_review else "study",
                "module": module_uid,
                "url": real_url,
                "review": is_review,
            })

        week_list = []
        milestones = timeline.get("milestones", [])
        for wk, sess in sorted(weeks.items())[:4]:
            ml = next((m for m in milestones if m.get("week") == wk), {})
            week_list.append({
                "week": wk,
                "milestone": ml.get("topics", [f"Week {wk}"])[0] if ml.get("topics") else f"Week {wk}",
                "target_mastery": ml.get("target_mastery", 0.5 + wk * 0.08),
                "sessions": sess,
            })

        total_min = sum(s.duration_minutes for s in sessions)
        return {
            "weeks": week_list,
            "total_days": timeline.get("total_study_days", 28),
            "exam_date": timeline.get("recommended_exam_date", (date.today() + timedelta(days=35)).isoformat()),
            "total_hours": round(total_min / 60, 1),
            "daily_commitment": 45,
        }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("Study plan generation failed: %s — using fallback", exc)
        from datetime import date, timedelta
        today = date.today()
        return {
            "weeks": [],
            "total_days": 28,
            "exam_date": (today + timedelta(days=35)).isoformat(),
            "total_hours": 0,
            "daily_commitment": 45,
        }


# ── Socratic Tutor ────────────────────────────────────────────────────────────

def get_tutor_response(
    topic: str,
    mastery: float,
    transcript: list[dict[str, str]],
) -> dict[str, Any]:
    """Get the next Socratic tutor response.

    transcript: list of {"role": "tutor"|"student", "content": "..."}

    Returns dict with: tutor_message, bloom_level, mastery_delta.
    """
    from agents.socratic_tutor import (
        SYSTEM_PROMPT_TEMPLATE,
        TutorMessage,
        bloom_for_mastery,
    )
    from models.student import BloomLevel

    async def _run():
        from integrations.azure_ai import AzureAIClient
        from integrations.learn_mcp import LearnMCPClient

        bloom, bloom_desc = bloom_for_mastery(mastery)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            bloom_level=bloom.value,
            bloom_description=bloom_desc,
        )

        # Build user message encoding full transcript
        parts = [f"Topic: {topic}", f"Current mastery: {mastery:.0%}"]

        # Fetch reference docs only for first turn
        if not transcript:
            try:
                async with LearnMCPClient() as mcp:
                    docs = await mcp.search_docs(topic, top=2)
                    if docs:
                        ref = "\n".join(f"- {d['title']}: {d['url']}" for d in docs)
                        parts.append(f"Reference docs:\n{ref}")
            except Exception:
                pass

        if transcript:
            parts.append("Conversation so far:")
            for msg in transcript:
                label = "Tutor" if msg["role"] == "tutor" else "Student"
                parts.append(f"[{label}]: {msg['content']}")
            parts.append("Continue the Socratic dialogue with your next question.")
        else:
            parts.append("Start the Socratic session with your opening question.")

        user_msg = "\n".join(parts)

        client = AzureAIClient()
        try:
            return await client.chat_completion_json(
                system_prompt, user_msg, temperature=0.6, max_tokens=600
            )
        finally:
            await client.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("Tutor response failed: %s", exc)
        return {
            "tutor_message": f"Let's explore {topic}. What do you already know about it?",
            "bloom_level": "remember",
            "mastery_delta": 0.0,
        }


# ── Assessment question ───────────────────────────────────────────────────────

def generate_assessment_question(
    objective: dict[str, Any],
    difficulty: str = "medium",
    cert_name: str = "Azure Fundamentals",
) -> dict[str, Any]:
    """Generate one assessment question (same as diagnostic but harder average)."""
    return generate_question(objective, difficulty=difficulty, cert_name=cert_name)
