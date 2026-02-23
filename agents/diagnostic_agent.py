"""CertBrain — Diagnostic Agent (Computerized Adaptive Testing).

Administers an adaptive pre-test that adjusts question difficulty in
real-time based on student responses.  Uses a simplified Item Response
Theory (IRT) model to estimate student ability (theta) per objective and
stops when the estimate converges or the question budget is exhausted.
"""

from __future__ import annotations

import math
import random
from typing import Any

from config import get_settings, get_logger
from integrations.azure_ai import AzureAIClient
from models.assessment import (
    Answer,
    AnswerOption,
    AssessmentResult,
    DiagnosticResult,
    Difficulty,
    Question,
    QuestionType,
)
from models.student import BloomLevel, ExamObjective

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_QUESTIONS = 10
MAX_QUESTIONS = 20
THETA_CONVERGENCE = 0.1  # stop when delta-theta < this between questions

# IRT-lite scoring deltas  (rows=correct/wrong, cols=difficulty)
_THETA_DELTA: dict[tuple[bool, Difficulty], float] = {
    (True, Difficulty.EASY): 0.15,
    (True, Difficulty.MEDIUM): 0.30,
    (True, Difficulty.HARD): 0.50,
    (False, Difficulty.EASY): -0.40,
    (False, Difficulty.MEDIUM): -0.25,
    (False, Difficulty.HARD): -0.10,
}

SYSTEM_PROMPT = """\
You are a Microsoft Certification Exam question generator.

## Your role
Generate realistic, exam-style multiple-choice questions for Microsoft \
certification exams.  Each question must:
- Test a SPECIFIC exam objective (provided in the user message).
- Have exactly 4 answer options (A, B, C, D) with exactly ONE correct answer.
- Match the requested difficulty level (easy / medium / hard).
- Include a detailed explanation for EVERY option stating why it is correct \
or incorrect, referencing official Microsoft documentation concepts.

## Difficulty guidelines
- **easy**: Generate a BASIC recall question. Test simple definitions and fundamental concepts.
  The student should be able to answer by remembering key terms.  Bloom level = REMEMBER.
- **medium**: Generate an APPLICATION-level question. Test understanding of how services work
  together. Include a realistic scenario.  Bloom level = UNDERSTAND / APPLY.
- **hard**: Generate an ANALYSIS or EVALUATION question. Present a complex multi-service
  scenario with trade-offs. The student must compare options and justify a choice.
  Bloom level = ANALYZE / EVALUATE.

## Output format — strict JSON, no markdown fences
{
  "stem": "<question text>",
  "options": [
    {"key": "A", "text": "<option text>", "is_correct": false},
    {"key": "B", "text": "<option text>", "is_correct": true},
    {"key": "C", "text": "<option text>", "is_correct": false},
    {"key": "D", "text": "<option text>", "is_correct": false}
  ],
  "explanation": "<detailed explanation for all options>",
  "bloom_level": "understand"
}
"""


# ---------------------------------------------------------------------------
# Option shuffler (prevents LLM position bias)
# ---------------------------------------------------------------------------
def _shuffle_options(options: list[AnswerOption]) -> list[AnswerOption]:
    """Randomly reorder options and re-assign keys A–D to the new positions.

    GPT-4o tends to place the correct answer at the same key position
    (usually B or C).  Shuffling after generation eliminates that bias.
    """
    shuffled = list(options)
    random.shuffle(shuffled)
    keys = [o.key for o in options]  # original key order (A, B, C, D)
    return [
        AnswerOption(key=keys[i], text=opt.text, is_correct=opt.is_correct)
        for i, opt in enumerate(shuffled)
    ]


# ---------------------------------------------------------------------------
# Diagnostic Agent
# ---------------------------------------------------------------------------
class DiagnosticAgent:
    """Adaptive diagnostic agent using simplified CAT / IRT.

    Parameters
    ----------
    certification_name:
        Human-readable cert name (e.g. "Azure Fundamentals").
    objectives:
        Exam objectives fetched from the Catalog API.
    """

    def __init__(
        self,
        certification_name: str,
        objectives: list[ExamObjective],
    ) -> None:
        self._cert_name = certification_name
        self._objectives = objectives
        self._settings = get_settings()

        # Per-objective ability estimate (theta) — starts at 0 (average)
        self._theta: dict[str, float] = {o.id: 0.0 for o in objectives}
        self._theta_history: dict[str, list[float]] = {o.id: [0.0] for o in objectives}

    # ------------------------------------------------------------------
    # Difficulty selector
    # ------------------------------------------------------------------
    @staticmethod
    def _select_difficulty(theta: float) -> Difficulty:
        """Map current theta to the next question difficulty (IRT fallback)."""
        if theta < -0.3:
            return Difficulty.EASY
        if theta > 0.3:
            return Difficulty.HARD
        return Difficulty.MEDIUM

    @staticmethod
    def _next_difficulty(current_difficulty: str, was_correct: bool) -> str:
        """Determine next question difficulty using CAT adaptation rules.

        Parameters
        ----------
        current_difficulty:
            Current difficulty level as uppercase string: "EASY", "MEDIUM", or "HARD".
        was_correct:
            Whether the student answered the previous question correctly.

        Returns
        -------
        str
            Next difficulty level as uppercase string.

        Examples
        --------
        - MEDIUM + correct  → HARD
        - HARD   + correct  → HARD   (capped)
        - MEDIUM + wrong    → EASY
        - EASY   + wrong    → EASY   (floored)
        """
        levels = ["EASY", "MEDIUM", "HARD"]
        current_idx = levels.index(current_difficulty.upper())

        if was_correct:
            next_idx = min(current_idx + 1, 2)
        else:
            next_idx = max(current_idx - 1, 0)

        return levels[next_idx]

    @staticmethod
    def _difficulty_to_bloom(difficulty: Difficulty) -> BloomLevel:
        return {
            Difficulty.EASY: BloomLevel.REMEMBER,
            Difficulty.MEDIUM: BloomLevel.UNDERSTAND,
            Difficulty.HARD: BloomLevel.ANALYZE,
        }[difficulty]

    # ------------------------------------------------------------------
    # LLM question generation
    # ------------------------------------------------------------------
    async def _generate_question(
        self,
        objective: ExamObjective,
        difficulty: Difficulty,
        azure_client: AzureAIClient,
    ) -> Question:
        """Ask the LLM to generate a single exam-style question."""
        _difficulty_instructions: dict[Difficulty, str] = {
            Difficulty.EASY: (
                "Generate a BASIC recall question. Test simple definitions and fundamental "
                "concepts. The student should answer by remembering key terms."
            ),
            Difficulty.MEDIUM: (
                "Generate an APPLICATION-level question. Test understanding of how services "
                "work together. Include a realistic scenario."
            ),
            Difficulty.HARD: (
                "Generate an ANALYSIS or EVALUATION question. Present a complex multi-service "
                "scenario with trade-offs. The student must compare options and justify a choice."
            ),
        }
        user_msg = (
            f"Certification: {self._cert_name}\n"
            f"Objective ID: {objective.id}\n"
            f"Objective: {objective.name}\n"
            f"Description: {objective.description}\n"
            f"Difficulty: {difficulty.value.upper()}\n"
            f"Instruction: {_difficulty_instructions[difficulty]}\n\n"
            "Generate ONE question in the JSON format specified."
        )

        try:
            data = await azure_client.chat_completion_json(
                SYSTEM_PROMPT, user_msg, temperature=0.7, max_tokens=800
            )
        except Exception as exc:
            logger.warning("LLM question generation failed: %s — using fallback", exc)
            data = self._fallback_question(objective, difficulty)

        bloom = BloomLevel(data.get("bloom_level", "understand"))
        options = [
            AnswerOption(
                key=opt["key"],
                text=opt["text"],
                is_correct=opt.get("is_correct", False),
            )
            for opt in data.get("options", [])
        ]
        # Safety: ensure exactly one correct option
        if sum(o.is_correct for o in options) != 1 and options:
            for o in options:
                o.is_correct = False
            options[0].is_correct = True

        # Shuffle options so the correct answer doesn't always land at the same key
        options = _shuffle_options(options)

        return Question(
            objective_id=objective.id,
            question_type=QuestionType.MULTIPLE_CHOICE,
            difficulty=difficulty,
            bloom_level=bloom,
            stem=data.get("stem", "Question generation error"),
            options=options,
            explanation=data.get("explanation", ""),
        )

    @staticmethod
    def _fallback_question(
        objective: ExamObjective, difficulty: Difficulty
    ) -> dict[str, Any]:
        """Return a hard-coded placeholder when the LLM is unavailable."""
        return {
            "stem": f"[Fallback] Which statement best describes '{objective.name}'?",
            "options": [
                {"key": "A", "text": f"It relates to {objective.name}", "is_correct": True},
                {"key": "B", "text": "It is unrelated to this exam", "is_correct": False},
                {"key": "C", "text": "It was deprecated last year", "is_correct": False},
                {"key": "D", "text": "None of the above", "is_correct": False},
            ],
            "explanation": "Fallback question — LLM was unavailable.",
            "bloom_level": "remember",
        }

    # ------------------------------------------------------------------
    # Theta update (IRT-lite)
    # ------------------------------------------------------------------
    def _update_theta(
        self, objective_id: str, correct: bool, difficulty: Difficulty
    ) -> float:
        """Update ability estimate and return the new theta."""
        delta = _THETA_DELTA.get((correct, difficulty), 0.0)
        old = self._theta[objective_id]
        new = max(-2.0, min(2.0, old + delta))  # clamp to [-2, 2]
        self._theta[objective_id] = new
        self._theta_history[objective_id].append(new)
        logger.debug(
            "theta[%s] %.2f → %.2f (correct=%s, diff=%s)",
            objective_id, old, new, correct, difficulty.value,
        )
        return new

    def _has_converged(self, objective_id: str) -> bool:
        """Check if theta for an objective has stabilised."""
        hist = self._theta_history[objective_id]
        if len(hist) < 3:
            return False
        return abs(hist[-1] - hist[-2]) < THETA_CONVERGENCE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run(
        self,
        student_id: str,
        answer_callback: Any | None = None,
    ) -> DiagnosticResult:
        """Execute the adaptive diagnostic test.

        Parameters
        ----------
        student_id:
            Unique student identifier.
        answer_callback:
            An async callable ``(question: Question) -> Answer``.
            If *None*, questions are auto-answered as incorrect (useful for
            unit-testing the CAT logic without a UI).

        Returns
        -------
        DiagnosticResult
        """
        logger.info(
            "Starting diagnostic for student=%s cert=%s (%d objectives)",
            student_id, self._cert_name, len(self._objectives),
        )

        all_questions: list[Question] = []
        all_answers: list[Answer] = []
        question_count = 0

        # CAT: track current difficulty per objective (all start at MEDIUM)
        cat_difficulty: dict[str, str] = {o.id: "MEDIUM" for o in self._objectives}

        azure_client = AzureAIClient()
        try:
            # Round-robin through objectives, adapting difficulty via CAT
            obj_idx = 0
            while question_count < MAX_QUESTIONS:
                objective = self._objectives[obj_idx % len(self._objectives)]
                obj_idx += 1

                # Skip objectives that have converged (after minimum)
                if question_count >= MIN_QUESTIONS and self._has_converged(objective.id):
                    # Check if ALL objectives have converged
                    if all(self._has_converged(o.id) for o in self._objectives):
                        logger.info("All thetas converged at question %d", question_count)
                        break
                    continue

                # Use CAT difficulty (starts MEDIUM, adapts based on previous answer)
                diff_str = cat_difficulty[objective.id]
                difficulty = Difficulty(diff_str.lower())

                question = await self._generate_question(
                    objective, difficulty, azure_client
                )
                all_questions.append(question)

                # Get student answer
                if answer_callback:
                    answer = await answer_callback(question)
                else:
                    # Auto-answer: incorrect (for testing)
                    answer = Answer(
                        question_id=question.id,
                        selected_keys=["X"],
                        is_correct=False,
                        confidence=0.5,
                    )

                all_answers.append(answer)
                self._update_theta(objective.id, answer.is_correct, difficulty)

                # Advance CAT difficulty for next question on this objective
                cat_difficulty[objective.id] = self._next_difficulty(diff_str, answer.is_correct)
                question_count += 1

                logger.info(
                    "Q%d/%d obj=%s diff=%s→%s correct=%s theta=%.2f",
                    question_count, MAX_QUESTIONS, objective.id,
                    diff_str, cat_difficulty[objective.id],
                    answer.is_correct, self._theta[objective.id],
                )
        finally:
            await azure_client.close()

        # Build assessment result
        assessment = AssessmentResult(
            student_id=student_id,
            questions=all_questions,
            answers=all_answers,
        )
        assessment.compute_scores(pass_threshold=self._settings.mastery_pass_threshold)

        # Map theta to mastery (sigmoid: mastery = 1 / (1 + e^(-theta)))
        mastery_map: dict[str, float] = {}
        for obj in self._objectives:
            theta = self._theta[obj.id]
            mastery_map[obj.id] = round(1.0 / (1.0 + math.exp(-theta)), 4)

        # Identify gaps and strengths
        threshold = self._settings.mastery_pass_threshold
        gaps = [oid for oid, m in mastery_map.items() if m < threshold]
        strengths = [oid for oid, m in mastery_map.items() if m >= threshold]

        # Recommend start objectives: weakest first
        recommended = sorted(gaps, key=lambda oid: mastery_map[oid])

        # Confidence calibration: correlation between confidence and correctness
        calibration = self._compute_calibration(all_answers)

        result = DiagnosticResult(
            student_id=student_id,
            assessment=assessment,
            identified_gaps=gaps,
            identified_strengths=strengths,
            recommended_start_objectives=recommended,
            confidence_calibration=calibration,
        )

        logger.info(
            "Diagnostic complete: score=%.2f gaps=%d strengths=%d calibration=%.2f",
            assessment.total_score, len(gaps), len(strengths), calibration,
        )
        return result

    @staticmethod
    def _compute_calibration(answers: list[Answer]) -> float:
        """Compute confidence–correctness correlation (-1 to 1)."""
        if len(answers) < 2:
            return 0.0
        n = len(answers)
        conf = [a.confidence for a in answers]
        corr = [1.0 if a.is_correct else 0.0 for a in answers]
        mean_c = sum(conf) / n
        mean_r = sum(corr) / n
        cov = sum((c - mean_c) * (r - mean_r) for c, r in zip(conf, corr)) / n
        std_c = math.sqrt(sum((c - mean_c) ** 2 for c in conf) / n) or 1e-9
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in corr) / n) or 1e-9
        return round(max(-1.0, min(1.0, cov / (std_c * std_r))), 4)

    @property
    def theta(self) -> dict[str, float]:
        """Current ability estimates per objective."""
        return dict(self._theta)

    @property
    def mastery_estimates(self) -> dict[str, float]:
        """Current mastery estimates (sigmoid of theta) per objective."""
        return {
            oid: round(1.0 / (1.0 + math.exp(-t)), 4)
            for oid, t in self._theta.items()
        }
