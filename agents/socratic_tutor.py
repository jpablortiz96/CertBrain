"""CertBrain — Socratic Tutor Agent (Bloom's Taxonomy).

An interactive teaching agent that NEVER gives direct answers.  Instead it
uses the Socratic method: asking progressively deeper questions that guide
the student toward understanding.  Question depth scales with mastery
through Bloom's taxonomy levels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import get_settings, get_logger
from integrations.azure_ai import AzureAIClient
from integrations.learn_mcp import LearnMCPClient
from models.knowledge_graph import KnowledgeGraph
from models.student import BloomLevel

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Bloom level selection based on mastery
# ---------------------------------------------------------------------------
_MASTERY_TO_BLOOM: list[tuple[float, BloomLevel, str]] = [
    (0.3, BloomLevel.REMEMBER, "recall and define core concepts"),
    (0.5, BloomLevel.APPLY, "apply concepts to practical scenarios"),
    (0.7, BloomLevel.ANALYZE, "compare, contrast, and explain WHY"),
    (0.9, BloomLevel.EVALUATE, "evaluate trade-offs and justify choices"),
    (1.1, BloomLevel.CREATE, "design original solutions and architectures"),
]


def bloom_for_mastery(mastery: float) -> tuple[BloomLevel, str]:
    """Select the appropriate Bloom level for a given mastery value."""
    for threshold, level, description in _MASTERY_TO_BLOOM:
        if mastery < threshold:
            return level, description
    return BloomLevel.CREATE, "design original solutions and architectures"


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """\
You are a Socratic Tutor specialising in Microsoft certification exam topics.

## Core principles
1. **NEVER give direct answers.** Always respond with a guiding question.
2. Adapt your questioning depth to the student's current Bloom level: {bloom_level}.
3. Your goal at this level: {bloom_description}.
4. When the student answers correctly, praise briefly then escalate to the next level.
5. When the student struggles, give a small hint (still as a question) and stay at the current level.
6. Ground your questions in official Microsoft documentation.

## Bloom level question starters
- REMEMBER: "Can you define…?", "What is…?", "List the…"
- UNDERSTAND: "In your own words, explain…", "Why does…?", "What would happen if…?"
- APPLY: "How would you use … to solve…?", "Implement a solution for…"
- ANALYZE: "Compare … and …", "What are the differences between…?", "Why does Azure use … instead of…?"
- EVALUATE: "Which approach is better for … and why?", "Critique this architecture…"
- CREATE: "Design a solution that…", "Propose an architecture for…"

## Response format — strict JSON, no markdown fences
{{
  "tutor_message": "<your Socratic question or hint>",
  "bloom_level": "{bloom_level}",
  "is_escalating": false,
  "hint_given": false,
  "mastery_delta": 0.0,
  "reference_url": ""
}}

- mastery_delta: suggest a change to the student's mastery for this topic:
  - +0.05 to +0.15 for a correct/insightful answer
  - -0.05 for a clearly wrong answer
  - 0.0 if you're still probing
- is_escalating: true when moving to a higher Bloom level
- hint_given: true when you had to give a hint
"""


@dataclass
class TutorMessage:
    """A single message in the tutoring session transcript."""

    role: str  # "tutor" | "student"
    content: str
    bloom_level: BloomLevel = BloomLevel.REMEMBER
    mastery_delta: float = 0.0


@dataclass
class TutorSessionResult:
    """Output of a completed tutoring session."""

    topic: str
    transcript: list[TutorMessage] = field(default_factory=list)
    initial_mastery: float = 0.0
    final_mastery: float = 0.0
    bloom_levels_reached: list[BloomLevel] = field(default_factory=list)
    reference_urls: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Socratic Tutor Agent
# ---------------------------------------------------------------------------
class SocraticTutorAgent:
    """Interactive tutor using Socratic method scaled by Bloom's taxonomy.

    Parameters
    ----------
    topic:
        The concept / objective being studied.
    mastery:
        Current student mastery for this topic (0-1).
    knowledge_graph:
        Full knowledge graph for context on related concepts.
    """

    def __init__(
        self,
        topic: str,
        mastery: float,
        knowledge_graph: KnowledgeGraph | None = None,
    ) -> None:
        self._topic = topic
        self._mastery = max(0.0, min(1.0, mastery))
        self._kg = knowledge_graph
        self._settings = get_settings()
        self._transcript: list[TutorMessage] = []
        self._reference_urls: list[str] = []

    # ------------------------------------------------------------------
    # Context enrichment
    # ------------------------------------------------------------------
    async def _fetch_reference(self) -> str:
        """Fetch documentation context from MS Learn MCP."""
        try:
            async with LearnMCPClient() as mcp:
                docs = await mcp.search_docs(self._topic, top=2)
                snippets: list[str] = []
                for doc in docs:
                    url = doc.get("url", "")
                    title = doc.get("title", doc.get("text", ""))
                    if url:
                        self._reference_urls.append(url)
                    snippets.append(f"- {title}: {url}")
                return "\n".join(snippets) if snippets else ""
        except Exception as exc:
            logger.warning("MCP reference fetch failed: %s", exc)
            return ""

    def _build_system_prompt(self) -> str:
        """Build the system prompt with current Bloom level."""
        bloom, desc = bloom_for_mastery(self._mastery)
        return SYSTEM_PROMPT_TEMPLATE.format(
            bloom_level=bloom.value,
            bloom_description=desc,
        )

    def _build_user_message(self, reference_context: str) -> str:
        """Build the user message encoding topic, mastery, and conversation history."""
        parts = [
            f"Topic: {self._topic}",
            f"Current mastery: {self._mastery:.0%}",
        ]
        if reference_context:
            parts.append(f"Reference docs:\n{reference_context}")
        if self._transcript:
            parts.append("Conversation so far:")
            for msg in self._transcript:
                label = "Tutor" if msg.role == "tutor" else "Student"
                parts.append(f"[{label}]: {msg.content}")
            parts.append("Continue the Socratic dialogue — respond with your next question.")
        else:
            parts.append("Start the Socratic session with your opening question.")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Single turn
    # ------------------------------------------------------------------
    async def ask(
        self,
        student_response: str | None = None,
        azure_client: AzureAIClient | None = None,
    ) -> TutorMessage:
        """Process one turn of the Socratic dialogue.

        Parameters
        ----------
        student_response:
            The student's latest answer.  Pass *None* for the opening question.
        azure_client:
            A pre-initialised AzureAIClient.  If *None*, one is created and closed.
        """
        # Record student message
        if student_response is not None:
            self._transcript.append(
                TutorMessage(role="student", content=student_response)
            )

        # Fetch docs on first turn
        reference_context = ""
        if len(self._transcript) <= 1:
            reference_context = await self._fetch_reference()

        system_prompt = self._build_system_prompt()
        user_msg = self._build_user_message(reference_context)

        close_client = azure_client is None
        if azure_client is None:
            azure_client = AzureAIClient()

        try:
            data = await azure_client.chat_completion_json(
                system_prompt, user_msg, temperature=0.6, max_tokens=600
            )
        except Exception as exc:
            logger.warning("Tutor LLM call failed: %s", exc)
            data = {
                "tutor_message": f"Let's explore {self._topic}. Can you tell me what you already know about it?",
                "bloom_level": "remember",
                "mastery_delta": 0.0,
            }
        finally:
            if close_client:
                await azure_client.close()

        # Update mastery
        delta = float(data.get("mastery_delta", 0.0))
        self._mastery = max(0.0, min(1.0, self._mastery + delta))

        bloom_str = data.get("bloom_level", "remember")
        try:
            bloom = BloomLevel(bloom_str)
        except ValueError:
            bloom = BloomLevel.REMEMBER

        ref_url = data.get("reference_url", "")
        if ref_url and ref_url not in self._reference_urls:
            self._reference_urls.append(ref_url)

        tutor_msg = TutorMessage(
            role="tutor",
            content=data.get("tutor_message", ""),
            bloom_level=bloom,
            mastery_delta=delta,
        )
        self._transcript.append(tutor_msg)

        logger.debug(
            "Tutor turn: bloom=%s delta=%.2f mastery=%.2f",
            bloom.value, delta, self._mastery,
        )
        return tutor_msg

    # ------------------------------------------------------------------
    # Full session loop
    # ------------------------------------------------------------------
    async def run_session(
        self,
        student_callback: Any,
        max_turns: int = 10,
    ) -> TutorSessionResult:
        """Run a full interactive tutoring session.

        Parameters
        ----------
        student_callback:
            Async callable ``(tutor_message: str) -> str`` that returns
            the student's response.
        max_turns:
            Maximum number of tutor–student exchanges.

        Returns
        -------
        TutorSessionResult
        """
        initial_mastery = self._mastery
        bloom_levels: list[BloomLevel] = []

        logger.info(
            "Starting Socratic session: topic=%s mastery=%.2f",
            self._topic, self._mastery,
        )

        azure_client = AzureAIClient()
        try:
            # Opening question
            tutor_msg = await self.ask(student_response=None, azure_client=azure_client)
            bloom_levels.append(tutor_msg.bloom_level)

            for turn in range(max_turns):
                # Get student response via callback
                student_text = await student_callback(tutor_msg.content)
                if student_text.strip().lower() in ("quit", "exit", "done"):
                    logger.info("Student ended session at turn %d", turn + 1)
                    break

                tutor_msg = await self.ask(
                    student_response=student_text,
                    azure_client=azure_client,
                )
                bloom_levels.append(tutor_msg.bloom_level)
        finally:
            await azure_client.close()

        result = TutorSessionResult(
            topic=self._topic,
            transcript=list(self._transcript),
            initial_mastery=initial_mastery,
            final_mastery=self._mastery,
            bloom_levels_reached=bloom_levels,
            reference_urls=list(self._reference_urls),
        )

        logger.info(
            "Socratic session done: %d turns, mastery %.2f → %.2f, peak bloom=%s",
            len(self._transcript),
            initial_mastery,
            self._mastery,
            bloom_levels[-1].value if bloom_levels else "n/a",
        )
        return result

    @property
    def mastery(self) -> float:
        """Current mastery estimate for this topic."""
        return self._mastery

    @property
    def transcript(self) -> list[TutorMessage]:
        """Full conversation transcript."""
        return list(self._transcript)
