"""CertBrain — Microsoft Learn search client.

Uses the public MS Learn Search API at
https://learn.microsoft.com/api/search
(no authentication required).

Exposes the same interface as the old MCP client so callers need no changes:

- **search_docs** — full-text search of Microsoft Learn
- **fetch_doc** — fetch a document's metadata by URL (via search)
- **search_code_samples** — search for code sample content

Reference:
    https://learn.microsoft.com/api/search?search=<query>&locale=en-us
"""

from __future__ import annotations

from typing import Any

import httpx

from config import get_settings, get_logger

logger = get_logger(__name__)

_SEARCH_URL = "https://learn.microsoft.com/api/search"
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


class MCPError(Exception):
    """Raised when the Learn search API returns an error."""


class LearnMCPClient:
    """Async client for Microsoft Learn search.

    Uses the public /api/search endpoint — no MCP protocol or auth needed.

    Usage::

        async with LearnMCPClient() as mcp:
            results = await mcp.search_docs("azure functions python")
    """

    def __init__(self, server_url: str | None = None) -> None:
        # server_url kept for interface compatibility but unused
        self._locale = get_settings().default_locale
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------
    async def __aenter__(self) -> LearnMCPClient:
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self._client

    # ------------------------------------------------------------------
    # Core search helper
    # ------------------------------------------------------------------
    async def _search(
        self,
        query: str,
        top: int = 5,
        locale: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Call the MS Learn Search API and return normalised results.

        Returns a list of dicts with keys: title, url, description.
        """
        client = self._ensure_client()
        params: dict[str, Any] = {
            "search": query,
            "locale": locale or self._locale,
            "$top": top,
        }
        if category:
            params["category"] = category

        logger.debug("Learn search: %r (top=%d)", query, top)
        try:
            response = await client.get(_SEARCH_URL, params=params)
        except httpx.RequestError as exc:
            raise MCPError(f"Learn search request failed: {exc}") from exc

        if response.status_code != 200:
            raise MCPError(
                f"Learn search returned {response.status_code}: {response.text[:300]}"
            )

        data: dict[str, Any] = response.json()
        raw_results: list[dict[str, Any]] = data.get("results", [])

        normalised: list[dict[str, Any]] = []
        for item in raw_results:
            normalised.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "locale": item.get("locale", locale or self._locale),
                "last_modified": item.get("lastModified", ""),
            })

        logger.info("Learn search(%r) returned %d results", query, len(normalised))
        return normalised

    # ------------------------------------------------------------------
    # Public interface (same signatures as original MCP client)
    # ------------------------------------------------------------------
    async def search_docs(
        self,
        query: str,
        top: int = 5,
        locale: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search Microsoft Learn documentation.

        Returns a list of dicts with ``title``, ``url``, ``description``.
        """
        return await self._search(query, top=top, locale=locale)

    async def fetch_doc(self, url: str) -> dict[str, Any]:
        """Return metadata for a specific Microsoft Learn document URL.

        Since the search API doesn't support direct fetch by URL, this
        searches for the URL's path as a query and returns the best match.
        """
        # Extract the meaningful part of the URL as search query
        query = url.split("/")[-1].replace("-", " ").replace("_", " ")
        results = await self._search(query, top=1)
        if results:
            return results[0]
        return {"title": "", "url": url, "description": ""}

    async def search_code_samples(
        self,
        query: str,
        top: int = 5,
    ) -> list[dict[str, Any]]:
        """Search Microsoft Learn code samples.

        Appends 'code sample' to the query and filters by category.
        """
        return await self._search(f"{query} code sample", top=top, category="Sample")
