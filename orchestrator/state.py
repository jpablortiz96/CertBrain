"""CertBrain — Shared session state (state machine).

Maintains the complete state of a certification-preparation session and
enforces valid phase transitions.  All data is Pydantic-serialisable so
it can be persisted to disk / database between interactions.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from config import get_logger
from models.assessment import AssessmentResult, DiagnosticResult
from models.student import StudentProfile, StudySession

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Phase enum & transitions
# ---------------------------------------------------------------------------
class Phase(str, Enum):
    """Ordered phases of the CertBrain pipeline."""

    DIAGNOSTIC = "diagnostic"
    BUILDING_GRAPH = "building_graph"
    PLANNING = "planning"
    CONFIRMING_PLAN = "confirming_plan"          # Human-in-the-loop #1
    STUDYING = "studying"
    READY_FOR_ASSESSMENT = "ready_for_assessment"  # Human-in-the-loop #2
    ASSESSING = "assessing"
    PASSED = "passed"
    NEEDS_REVIEW = "needs_review"


# Valid forward transitions: current_phase -> set of reachable next phases
_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.DIAGNOSTIC:            {Phase.BUILDING_GRAPH},
    Phase.BUILDING_GRAPH:        {Phase.PLANNING},
    Phase.PLANNING:              {Phase.CONFIRMING_PLAN},
    Phase.CONFIRMING_PLAN:       {Phase.STUDYING},
    Phase.STUDYING:              {Phase.READY_FOR_ASSESSMENT, Phase.STUDYING},
    Phase.READY_FOR_ASSESSMENT:  {Phase.ASSESSING},
    Phase.ASSESSING:             {Phase.PASSED, Phase.NEEDS_REVIEW},
    Phase.NEEDS_REVIEW:          {Phase.PLANNING},  # loop back
    Phase.PASSED:                set(),               # terminal
}

# Conditions that must be true to *leave* a phase
_PHASE_REQUIREMENTS: dict[Phase, str] = {
    Phase.DIAGNOSTIC:           "diagnostic_result",
    Phase.BUILDING_GRAPH:       "knowledge_graph",
    Phase.PLANNING:             "study_plan",
    Phase.CONFIRMING_PLAN:      "_plan_confirmed",
    Phase.STUDYING:             "_has_tutor_sessions",
    Phase.READY_FOR_ASSESSMENT: "_assessment_ready_confirmed",
    Phase.ASSESSING:            "_has_assessment_results",
}


# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------
class CertBrainState(BaseModel):
    """Complete state of a CertBrain certification-prep session."""

    session_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    student: StudentProfile = Field(default_factory=lambda: StudentProfile(name=""))
    certification_name: str = ""
    exam_uid: str = ""

    current_phase: Phase = Phase.DIAGNOSTIC

    # Agent outputs
    diagnostic_result: DiagnosticResult | None = None
    knowledge_graph: dict[str, Any] | None = None  # serialised KG via .to_dict()
    study_plan: list[StudySession] | None = None
    timeline: dict[str, Any] | None = None
    tutor_sessions: list[dict[str, Any]] = Field(default_factory=list)
    assessment_results: list[AssessmentResult] = Field(default_factory=list)
    verification_log: list[dict[str, Any]] = Field(default_factory=list)
    reminders: list[dict[str, Any]] = Field(default_factory=list)

    # Loop tracking
    iteration_count: int = 0
    max_iterations: int = 3

    # Human-in-the-loop flags
    plan_confirmed: bool = False
    assessment_ready_confirmed: bool = False

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # ------------------------------------------------------------------
    # Phase-requirement checkers (used by can_advance)
    # ------------------------------------------------------------------
    @property
    def _plan_confirmed(self) -> bool:
        return self.plan_confirmed

    @property
    def _assessment_ready_confirmed(self) -> bool:
        return self.assessment_ready_confirmed

    @property
    def _has_tutor_sessions(self) -> bool:
        return len(self.tutor_sessions) > 0

    @property
    def _has_assessment_results(self) -> bool:
        return len(self.assessment_results) > 0

    # ------------------------------------------------------------------
    # State machine logic
    # ------------------------------------------------------------------
    def can_advance(self, target: Phase) -> tuple[bool, str]:
        """Check whether transitioning to *target* is valid.

        Returns ``(ok, reason)`` — *reason* explains the failure when
        *ok* is ``False``.
        """
        allowed = _TRANSITIONS.get(self.current_phase, set())
        if target not in allowed:
            return False, (
                f"Cannot go from {self.current_phase.value} to {target.value}. "
                f"Allowed: {[p.value for p in allowed]}"
            )

        # Check that the current phase's exit condition is met
        req_attr = _PHASE_REQUIREMENTS.get(self.current_phase)
        if req_attr:
            value = getattr(self, req_attr, None)
            if not value:
                return False, (
                    f"Phase {self.current_phase.value} not complete: "
                    f"'{req_attr}' is empty/None"
                )

        return True, ""

    def advance_phase(self, target: Phase) -> None:
        """Transition to *target* phase, raising ``ValueError`` if invalid."""
        ok, reason = self.can_advance(target)
        if not ok:
            raise ValueError(reason)

        old = self.current_phase
        self.current_phase = target
        self.updated_at = datetime.utcnow()

        if target == Phase.NEEDS_REVIEW:
            self.iteration_count += 1

        logger.info(
            "Phase transition: %s -> %s  (session=%s, iteration=%d)",
            old.value, target.value, self.session_id, self.iteration_count,
        )

    def should_loop_back(self) -> bool:
        """Return *True* if the student failed and can retry."""
        return (
            self.current_phase == Phase.NEEDS_REVIEW
            and self.iteration_count < self.max_iterations
        )

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------
    _PHASE_WEIGHT: dict[Phase, int] = {
        Phase.DIAGNOSTIC: 10,
        Phase.BUILDING_GRAPH: 20,
        Phase.PLANNING: 35,
        Phase.CONFIRMING_PLAN: 40,
        Phase.STUDYING: 65,
        Phase.READY_FOR_ASSESSMENT: 75,
        Phase.ASSESSING: 90,
        Phase.PASSED: 100,
        Phase.NEEDS_REVIEW: 70,
    }

    def get_progress_percentage(self) -> int:
        """Return approximate pipeline progress as 0-100."""
        return self._PHASE_WEIGHT.get(self.current_phase, 0)

    # ------------------------------------------------------------------
    # Verification log helpers
    # ------------------------------------------------------------------
    def add_verification(self, agent_name: str, result: dict[str, Any]) -> None:
        """Append a critic verification entry to the log."""
        self.verification_log.append({
            "agent": agent_name,
            "timestamp": datetime.utcnow().isoformat(),
            **result,
        })
        self.updated_at = datetime.utcnow()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_json(self) -> str:
        """Serialise the full state to a JSON string."""
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> CertBrainState:
        """Deserialise a JSON string into a CertBrainState."""
        return cls.model_validate_json(data)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CertBrainState:
        """Deserialise from a plain dict."""
        return cls.model_validate(data)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
    def summary(self) -> str:
        """Human-readable one-line summary."""
        return (
            f"[{self.session_id}] {self.student.name} | "
            f"{self.certification_name} | phase={self.current_phase.value} | "
            f"mastery={self.student.overall_mastery:.0%} | "
            f"progress={self.get_progress_percentage()}% | "
            f"iter={self.iteration_count}"
        )

    def __repr__(self) -> str:
        return (
            f"CertBrainState(session={self.session_id!r}, "
            f"phase={self.current_phase.value!r}, "
            f"student={self.student.name!r})"
        )
