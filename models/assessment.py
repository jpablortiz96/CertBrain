"""CertBrain — Assessment-related Pydantic models.

Data structures for diagnostic and practice questions, student answers,
assessment results, and diagnostic summaries.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from models.student import BloomLevel


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class QuestionType(str, Enum):
    """Supported question formats."""

    MULTIPLE_CHOICE = "multiple_choice"
    MULTIPLE_SELECT = "multiple_select"
    TRUE_FALSE = "true_false"
    SCENARIO = "scenario"
    DRAG_AND_DROP = "drag_and_drop"


class Difficulty(str, Enum):
    """Question difficulty tier."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


# ---------------------------------------------------------------------------
# Question & answer
# ---------------------------------------------------------------------------
class AnswerOption(BaseModel):
    """A single selectable option within a question."""

    key: str = Field(description="Option key (A, B, C, …)")
    text: str = Field(description="Option text")
    is_correct: bool = Field(default=False)


class Question(BaseModel):
    """An assessment question tied to one or more exam objectives."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    objective_id: str = Field(description="Primary ExamObjective.id this tests")
    question_type: QuestionType = Field(default=QuestionType.MULTIPLE_CHOICE)
    difficulty: Difficulty = Field(default=Difficulty.MEDIUM)
    bloom_level: BloomLevel = Field(default=BloomLevel.UNDERSTAND)

    stem: str = Field(description="The question text / prompt")
    options: list[AnswerOption] = Field(default_factory=list)
    explanation: str = Field(
        default="",
        description="Detailed explanation shown after answering",
    )
    reference_url: str = Field(
        default="",
        description="Microsoft Learn URL backing this question",
    )


class Answer(BaseModel):
    """A student's response to a single question."""

    question_id: str
    selected_keys: list[str] = Field(
        description="Keys chosen by the student (e.g. ['A', 'C'])",
    )
    is_correct: bool = Field(default=False)
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Self-reported confidence (0-1)",
    )
    time_taken_seconds: float = Field(default=0.0, ge=0.0)
    answered_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Assessment result (per-session roll-up)
# ---------------------------------------------------------------------------
class ObjectiveScore(BaseModel):
    """Score breakdown for a single objective within an assessment."""

    objective_id: str
    questions_total: int = 0
    questions_correct: int = 0
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_time_seconds: float = Field(default=0.0, ge=0.0)


class AssessmentResult(BaseModel):
    """Aggregated result of a practice/assessment session."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    student_id: str
    questions: list[Question] = Field(default_factory=list)
    answers: list[Answer] = Field(default_factory=list)
    objective_scores: list[ObjectiveScore] = Field(default_factory=list)

    total_score: float = Field(default=0.0, ge=0.0, le=1.0)
    passed: bool = Field(default=False)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = Field(default=None)

    def compute_scores(self, pass_threshold: float = 0.80) -> None:
        """Populate ``objective_scores`` and ``total_score`` from answers.

        Parameters
        ----------
        pass_threshold:
            Minimum total score to set ``passed = True``.
        """
        # Build lookup: question_id → question
        q_map: dict[str, Question] = {q.id: q for q in self.questions}

        # Group answers by objective
        obj_answers: dict[str, list[Answer]] = {}
        for ans in self.answers:
            q = q_map.get(ans.question_id)
            if not q:
                continue
            obj_answers.setdefault(q.objective_id, []).append(ans)

        scores: list[ObjectiveScore] = []
        for obj_id, answers in obj_answers.items():
            correct = sum(1 for a in answers if a.is_correct)
            total = len(answers)
            scores.append(
                ObjectiveScore(
                    objective_id=obj_id,
                    questions_total=total,
                    questions_correct=correct,
                    score=round(correct / total, 4) if total else 0.0,
                    avg_confidence=round(
                        sum(a.confidence for a in answers) / total, 4
                    )
                    if total
                    else 0.0,
                    avg_time_seconds=round(
                        sum(a.time_taken_seconds for a in answers) / total, 2
                    )
                    if total
                    else 0.0,
                )
            )

        self.objective_scores = scores
        total_q = sum(s.questions_total for s in scores)
        total_c = sum(s.questions_correct for s in scores)
        self.total_score = round(total_c / total_q, 4) if total_q else 0.0
        self.passed = self.total_score >= pass_threshold


# ---------------------------------------------------------------------------
# Diagnostic result (initial knowledge probe)
# ---------------------------------------------------------------------------
class DiagnosticResult(BaseModel):
    """Output of the diagnostic agent — drives knowledge graph seeding."""

    student_id: str
    assessment: AssessmentResult
    identified_gaps: list[str] = Field(
        default_factory=list,
        description="Objective IDs where mastery < threshold",
    )
    identified_strengths: list[str] = Field(
        default_factory=list,
        description="Objective IDs where mastery >= threshold",
    )
    recommended_start_objectives: list[str] = Field(
        default_factory=list,
        description="Ordered list of objective IDs to study first",
    )
    confidence_calibration: float = Field(
        default=0.0,
        description="How well student confidence correlates with correctness (-1 to 1)",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
