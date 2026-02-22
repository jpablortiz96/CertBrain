"""CertBrain — Student-related Pydantic models.

Defines the core data structures for student profiles, exam objectives,
and study sessions used throughout the orchestration pipeline.
"""

from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class BloomLevel(str, Enum):
    """Bloom's taxonomy cognitive levels (low → high)."""

    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


class SessionStatus(str, Enum):
    """Lifecycle status of a study session."""

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Exam objective
# ---------------------------------------------------------------------------
class ExamObjective(BaseModel):
    """A single objective/skill measured by a certification exam."""

    id: str = Field(description="Unique objective identifier (e.g. 'AZ-900-1.1')")
    name: str = Field(description="Short name of the objective")
    description: str = Field(default="", description="Detailed description")
    weight_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage weight on the exam",
    )
    bloom_level: BloomLevel = Field(
        default=BloomLevel.UNDERSTAND,
        description="Target cognitive level for this objective",
    )
    mastery: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Current mastery estimate (0-1)",
    )


# ---------------------------------------------------------------------------
# Study session
# ---------------------------------------------------------------------------
class StudySession(BaseModel):
    """Record of a single study session (planned or completed)."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    objective_id: str = Field(description="Related ExamObjective.id")
    module_uid: str = Field(
        default="",
        description="Microsoft Learn module UID mapped to this session",
    )
    scheduled_date: date = Field(description="Date the session is planned for")
    status: SessionStatus = Field(default=SessionStatus.SCHEDULED)
    duration_minutes: int = Field(default=0, ge=0)
    bloom_target: BloomLevel = Field(default=BloomLevel.UNDERSTAND)

    # SM-2 spaced repetition fields
    easiness_factor: float = Field(default=2.5, ge=1.3)
    interval_days: int = Field(default=1, ge=1)
    repetition_number: int = Field(default=0, ge=0)
    next_review_date: date | None = Field(default=None)

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    notes: str = Field(default="")


# ---------------------------------------------------------------------------
# Student profile (root aggregate)
# ---------------------------------------------------------------------------
class StudentProfile(BaseModel):
    """Complete profile for a student preparing for a certification exam."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = Field(description="Student display name")
    email: str = Field(default="", description="Contact email for reminders")

    # Target certification
    certification_uid: str = Field(
        default="",
        description="Microsoft Learn certification UID (e.g. 'certification.azure-fundamentals')",
    )
    exam_uid: str = Field(
        default="",
        description="Microsoft Learn exam UID (e.g. 'exam.az-900')",
    )

    # Objectives & sessions
    objectives: list[ExamObjective] = Field(default_factory=list)
    study_sessions: list[StudySession] = Field(default_factory=list)

    # Diagnostic results summary
    overall_mastery: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Aggregate mastery across all objectives (0-1)",
    )
    diagnostic_completed: bool = Field(default=False)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------
    def get_weak_objectives(self, threshold: float = 0.5) -> list[ExamObjective]:
        """Return objectives where mastery is below *threshold*."""
        return [o for o in self.objectives if o.mastery < threshold]

    def recalculate_mastery(self) -> float:
        """Recompute ``overall_mastery`` as weighted average of objectives."""
        if not self.objectives:
            return 0.0
        total_weight = sum(o.weight_percent for o in self.objectives) or 1.0
        weighted = sum(o.mastery * o.weight_percent for o in self.objectives)
        self.overall_mastery = round(weighted / total_weight, 4)
        self.updated_at = datetime.utcnow()
        return self.overall_mastery

    def pending_sessions(self) -> list[StudySession]:
        """Return sessions that are still scheduled (not completed/skipped)."""
        return [
            s
            for s in self.study_sessions
            if s.status in (SessionStatus.SCHEDULED, SessionStatus.IN_PROGRESS)
        ]
