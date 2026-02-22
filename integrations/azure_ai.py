"""CertBrain — Centralized Azure AI Inference client.

Uses azure.ai.inference with DefaultAzureCredential (scope: https://ai.azure.com/.default).
The correct inference endpoint for Azure AI Foundry is:
  https://<resource>.services.ai.azure.com/models

All calls include retry logic (3 attempts, exponential backoff) and
structured logging (tokens used, latency, model).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Type, TypeVar

from azure.ai.inference.aio import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.identity.aio import DefaultAzureCredential
from pydantic import BaseModel

from config import get_settings, get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.5  # seconds


# ---------------------------------------------------------------------------
# Credential wrapper: locks scope to https://ai.azure.com/.default
# ---------------------------------------------------------------------------
class _FoundryCredential:
    """Wraps DefaultAzureCredential to always use the AI Foundry scope."""

    def __init__(self) -> None:
        self._inner = DefaultAzureCredential()

    async def get_token(self, *scopes: str, **kwargs: Any):
        return await self._inner.get_token("https://ai.azure.com/.default")

    async def close(self) -> None:
        await self._inner.close()


# ---------------------------------------------------------------------------
# Azure AI Client
# ---------------------------------------------------------------------------
class AzureAIClient:
    """Async client for Azure AI Foundry inference (azure.ai.inference).

    Usage::

        async with AzureAIClient() as client:
            text = await client.chat_completion(system, user)
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._endpoint = settings.project_endpoint
        self._model = settings.model_deployment_name

        # Derive the models endpoint from the project endpoint
        # Project: https://xxx.services.ai.azure.com/api/projects/certbrain
        # Models:  https://xxx.services.ai.azure.com/models
        import re
        base = re.match(r"(https://[^/]+)", self._endpoint)
        if not base:
            raise ValueError(
                f"Cannot derive models endpoint from PROJECT_ENDPOINT: {self._endpoint!r}\n"
                "Expected format: https://<resource>.services.ai.azure.com/api/projects/<project>"
            )
        self._models_endpoint = base.group(1) + "/models"
        self._cred: _FoundryCredential | None = None
        self._client: ChatCompletionsClient | None = None

    async def __aenter__(self) -> AzureAIClient:
        self._cred = _FoundryCredential()
        self._client = ChatCompletionsClient(
            endpoint=self._models_endpoint,
            credential=self._cred,
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
        if self._cred:
            await self._cred.close()
            self._cred = None

    def _ensure_client(self) -> ChatCompletionsClient:
        if self._client is None:
            self._cred = _FoundryCredential()
            self._client = ChatCompletionsClient(
                endpoint=self._models_endpoint,
                credential=self._cred,
            )
        return self._client

    # ------------------------------------------------------------------
    # Core call with retry
    # ------------------------------------------------------------------
    async def _call(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> tuple[str, dict[str, int]]:
        """Execute a chat completion with retry logic.

        Returns ``(content, usage_dict)``.
        """
        client = self._ensure_client()
        extra_kwargs: dict[str, Any] = {}
        if json_mode:
            extra_kwargs["response_format"] = "json_object"  # azure.ai.inference literal

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            t0 = time.perf_counter()
            try:
                response = await client.complete(
                    messages=[
                        SystemMessage(system_prompt),
                        UserMessage(user_message),
                    ],
                    model=self._model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **extra_kwargs,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                }
                content = response.choices[0].message.content or ""
                logger.debug(
                    "LLM call OK: model=%s tokens=%d latency=%dms attempt=%d",
                    self._model, usage["total_tokens"], latency_ms, attempt,
                )
                return content, usage

            except Exception as exc:
                last_exc = exc
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt, _MAX_RETRIES, exc, delay,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)

        raise RuntimeError(
            f"Azure AI call failed after {_MAX_RETRIES} attempts. "
            f"Last error: {last_exc}\n"
            f"Check: PROJECT_ENDPOINT and MODEL_DEPLOYMENT_NAME in .env, "
            f"and that you have run 'az login'."
        ) from last_exc

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    async def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        """Return the raw text response from the model."""
        content, _ = await self._call(system_prompt, user_message, temperature, max_tokens)
        return content

    async def chat_completion_json(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        """Return parsed JSON dict from a JSON-mode response.

        Raises ``ValueError`` if the response is not valid JSON.
        """
        content, _ = await self._call(
            system_prompt, user_message, temperature, max_tokens, json_mode=True
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Model returned non-JSON response: {content[:200]!r}"
            ) from exc

    async def chat_completion_structured(
        self,
        system_prompt: str,
        user_message: str,
        response_format: Type[T],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> T:
        """Return a Pydantic model parsed from the JSON response."""
        data = await self.chat_completion_json(
            system_prompt, user_message, temperature, max_tokens
        )
        return response_format.model_validate(data)
