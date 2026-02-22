"""CertBrain — Critic / Verifier Agent.

Reviews ANY agent output for technical accuracy by cross-referencing against
official Microsoft Learn documentation via the MCP server.  When the initial
confidence score is below a threshold, it triggers SELF-REFLECTION: a second
analysis pass with a contrarian prompt, then reconciles both results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from config import get_settings, get_logger
from integrations.azure_ai import AzureAIClient
from integrations.learn_mcp import LearnMCPClient

logger = get_logger(__name__)

CONFIDENCE_THRESHOLD = 0.70

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
VERIFY_SYSTEM_PROMPT = """\
You are a Technical Accuracy Critic for Microsoft certification content.

## Your role
Given content produced by another AI agent (questions, knowledge graphs, \
study plans, tutor responses), you must:
1. Check every technical claim against your knowledge of Microsoft technologies.
2. Identify factual errors, outdated information, or misleading statements.
3. Assign a confidence score (0.0-1.0) reflecting how certain you are the content is accurate.
4. List specific issues found and suggest corrections.

## Reference documentation
{reference_docs}

## Output format — strict JSON, no markdown fences
{{
  "is_valid": true,
  "confidence": 0.85,
  "issues": [
    {{"claim": "<problematic claim>", "severity": "high|medium|low", "explanation": "<why it's wrong>", "correction": "<correct information>"}}
  ],
  "corrections": ["<corrected statement 1>", "<corrected statement 2>"],
  "sources": ["<MS Learn URL 1>", "<MS Learn URL 2>"],
  "summary": "<1-2 sentence overall assessment>"
}}

## Rules
- Be strict: if you're uncertain, lower confidence and flag it.
- severity: "high" = factually wrong, "medium" = misleading, "low" = imprecise.
- sources: only list real Microsoft Learn URLs from the reference docs provided.
- is_valid = false if any HIGH severity issues are found.
"""

REFLECTION_SYSTEM_PROMPT = """\
You are a Devil's Advocate Reviewer for Microsoft technical content.

## Your role
A previous review found this content acceptable with confidence {prev_confidence:.0%}.
Your job is to CHALLENGE that assessment:
1. Actively look for errors the first reviewer may have missed.
2. Consider edge cases, version-specific differences, and common misconceptions.
3. Be especially critical of any claims that sound plausible but might be subtly wrong.

## Reference documentation
{reference_docs}

## Output format — strict JSON, no markdown fences
{{
  "additional_issues": [
    {{"claim": "<claim>", "severity": "high|medium|low", "explanation": "<why>"}}
  ],
  "revised_confidence": 0.75,
  "agrees_with_first_review": true,
  "notes": "<any additional observations>"
}}
"""


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------
@dataclass
class VerificationResult:
    """Structured output of the Critic Agent."""

    is_valid: bool = True
    confidence: float = 0.0
    issues: list[dict[str, str]] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    summary: str = ""
    self_reflection_triggered: bool = False


# ---------------------------------------------------------------------------
# Critic Agent
# ---------------------------------------------------------------------------
class CriticAgent:
    """Verifies agent outputs for technical accuracy.

    Parameters
    ----------
    content_to_verify:
        The agent output to verify (as a string or JSON-serialisable object).
    content_type:
        A label describing what is being verified (e.g. ``"diagnostic_questions"``,
        ``"knowledge_graph"``, ``"study_plan"``, ``"tutor_response"``).
    """

    def __init__(
        self,
        content_to_verify: Any,
        content_type: str = "agent_output",
    ) -> None:
        if isinstance(content_to_verify, str):
            self._content = content_to_verify
        else:
            try:
                self._content = json.dumps(content_to_verify, default=str, indent=2)
            except TypeError:
                self._content = str(content_to_verify)
        self._content_type = content_type
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # MCP reference fetching
    # ------------------------------------------------------------------
    async def _fetch_references(self) -> str:
        """Search MS Learn for topics mentioned in the content."""
        # Extract key terms (first 200 chars as search query, simplified)
        query = self._content[:200].replace("\n", " ").strip()
        docs_text = ""
        try:
            async with LearnMCPClient() as mcp:
                results = await mcp.search_docs(query, top=3)
                lines: list[str] = []
                for doc in results:
                    title = doc.get("title", doc.get("text", ""))
                    url = doc.get("url", "")
                    lines.append(f"- {title}: {url}")
                docs_text = "\n".join(lines)
        except Exception as exc:
            logger.warning("MCP reference fetch failed: %s", exc)
        return docs_text or "No reference documentation available."

    # ------------------------------------------------------------------
    # Verification passes
    # ------------------------------------------------------------------
    async def _first_pass(
        self, azure_client: AzureAIClient, reference_docs: str
    ) -> dict[str, Any]:
        """Run the primary verification pass."""
        system_prompt = VERIFY_SYSTEM_PROMPT.format(reference_docs=reference_docs)
        user_msg = (
            f"Content type: {self._content_type}\n\n"
            f"Content to verify:\n{self._content[:4000]}"
        )

        try:
            return await azure_client.chat_completion_json(
                system_prompt, user_msg, temperature=0.2, max_tokens=1500
            )
        except Exception as exc:
            logger.warning("First verification pass failed: %s", exc)
            return {
                "is_valid": True,
                "confidence": 0.5,
                "issues": [],
                "corrections": [],
                "sources": [],
                "summary": f"Verification failed: {exc}",
            }

    async def _reflection_pass(
        self,
        azure_client: AzureAIClient,
        reference_docs: str,
        first_pass_confidence: float,
    ) -> dict[str, Any]:
        """Run the self-reflection (devil's advocate) pass."""
        system_prompt = REFLECTION_SYSTEM_PROMPT.format(
            prev_confidence=first_pass_confidence,
            reference_docs=reference_docs,
        )
        user_msg = (
            f"Content type: {self._content_type}\n\n"
            f"Content to verify:\n{self._content[:4000]}\n\n"
            f"First review confidence: {first_pass_confidence:.0%}"
        )

        try:
            return await azure_client.chat_completion_json(
                system_prompt, user_msg, temperature=0.4, max_tokens=1000
            )
        except Exception as exc:
            logger.warning("Self-reflection pass failed: %s", exc)
            return {
                "additional_issues": [],
                "revised_confidence": first_pass_confidence,
                "agrees_with_first_review": True,
                "notes": f"Reflection failed: {exc}",
            }

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------
    @staticmethod
    def _reconcile(
        first: dict[str, Any], reflection: dict[str, Any]
    ) -> VerificationResult:
        """Merge first-pass and reflection results."""
        all_issues = list(first.get("issues", []))
        for issue in reflection.get("additional_issues", []):
            all_issues.append(issue)

        # Use the more conservative confidence
        confidence = min(
            first.get("confidence", 0.5),
            reflection.get("revised_confidence", first.get("confidence", 0.5)),
        )

        has_high = any(i.get("severity") == "high" for i in all_issues)
        is_valid = not has_high and confidence >= 0.5

        return VerificationResult(
            is_valid=is_valid,
            confidence=confidence,
            issues=all_issues,
            corrections=first.get("corrections", []),
            sources=first.get("sources", []),
            summary=first.get("summary", ""),
            self_reflection_triggered=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run(self) -> VerificationResult:
        """Verify the content, triggering self-reflection if needed.

        Returns
        -------
        VerificationResult
        """
        logger.info("Critic verifying %s (%d chars)", self._content_type, len(self._content))

        reference_docs = await self._fetch_references()

        azure_client = AzureAIClient()
        try:
            # First pass
            first = await self._first_pass(azure_client, reference_docs)
            confidence = first.get("confidence", 0.5)
            logger.info("First pass confidence: %.2f", confidence)

            # Self-reflection if below threshold
            if confidence < CONFIDENCE_THRESHOLD:
                logger.info(
                    "Confidence %.2f < %.2f — triggering self-reflection",
                    confidence, CONFIDENCE_THRESHOLD,
                )
                reflection = await self._reflection_pass(
                    azure_client, reference_docs, confidence
                )
                result = self._reconcile(first, reflection)
            else:
                has_high = any(
                    i.get("severity") == "high" for i in first.get("issues", [])
                )
                result = VerificationResult(
                    is_valid=first.get("is_valid", True) and not has_high,
                    confidence=confidence,
                    issues=first.get("issues", []),
                    corrections=first.get("corrections", []),
                    sources=first.get("sources", []),
                    summary=first.get("summary", ""),
                    self_reflection_triggered=False,
                )
        finally:
            await azure_client.close()

        logger.info(
            "Critic result: valid=%s confidence=%.2f issues=%d reflected=%s",
            result.is_valid, result.confidence, len(result.issues),
            result.self_reflection_triggered,
        )
        return result
