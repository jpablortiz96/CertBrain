"""CertBrain — Microsoft Learn Catalog API client.

Wraps the public (no auth) REST API at
https://learn.microsoft.com/api/catalog/ to fetch certifications, exams,
learning paths, and modules.

Reference:
    https://learn.microsoft.com/en-us/training/support/catalog-api

Notes on AZ-900:
    The exam 'exam.az-900' is NOT in the /api/catalog/?type=exams response.
    Use 'certification.azure-fundamentals' or search learning paths by
    products/title containing 'azure-fundamentals'.
"""

from __future__ import annotations

from typing import Any

import httpx

from config import get_settings, get_logger

logger = get_logger(__name__)

_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# Map common exam codes to search terms for learning path lookup
_EXAM_SEARCH_ALIASES: dict[str, list[str]] = {
    "az-900": ["azure-fundamentals", "az-900"],
    "az-104": ["azure-administrator", "az-104"],
    "az-204": ["azure-developer", "az-204"],
    "az-305": ["azure-solutions-architect", "az-305"],
    "az-400": ["azure-devops", "az-400"],
    "sc-900": ["security-compliance-identity", "sc-900"],
    "ai-900": ["azure-ai-fundamentals", "ai-900"],
}


class CatalogAPIError(Exception):
    """Raised when the Catalog API returns an unexpected response."""


class CatalogAPIClient:
    """Async client for the Microsoft Learn Catalog API.

    Usage::

        async with CatalogAPIClient() as client:
            certs = await client.get_certifications()
    """

    def __init__(self, base_url: str | None = None, locale: str | None = None) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.catalog_api_base_url).rstrip("/")
        self._locale = locale or settings.default_locale
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------
    async def __aenter__(self) -> CatalogAPIClient:
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self._client

    async def _get(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform a GET request to the catalog endpoint."""
        client = self._ensure_client()
        merged: dict[str, Any] = {"locale": self._locale}
        if params:
            merged.update(params)

        logger.debug("GET %s params=%s", self._base_url, merged)
        response = await client.get(self._base_url, params=merged)

        if response.status_code != 200:
            raise CatalogAPIError(
                f"Catalog API returned {response.status_code}: {response.text[:300]}"
            )

        data: dict[str, Any] = response.json()
        return data

    @staticmethod
    def _exam_uid_to_code(exam_uid: str) -> str:
        """Normalise exam UID to a short code, e.g. 'exam.az-900' → 'az-900'."""
        return exam_uid.lower().replace("exam.", "").replace("certification.", "").strip()

    @staticmethod
    def _search_terms(exam_uid: str) -> list[str]:
        """Return search terms for matching learning paths to an exam."""
        code = CatalogAPIClient._exam_uid_to_code(exam_uid)
        aliases = _EXAM_SEARCH_ALIASES.get(code, [code])
        return [t.lower() for t in aliases]

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------
    async def get_certifications(self) -> list[dict[str, Any]]:
        """Fetch all Microsoft certifications.

        Each cert has: uid, title, subtitle, url, levels, roles, products,
        exams (list of exam UIDs), study_guide (list of areas, often empty).
        """
        data = await self._get(params={"type": "certifications"})
        certs = data.get("certifications", [])
        logger.info("Fetched %d certifications", len(certs))
        return certs

    async def get_certification_by_uid(self, uid: str) -> dict[str, Any] | None:
        """Return a single certification dict by UID, or None if not found."""
        certs = await self.get_certifications()
        uid_lower = uid.lower()
        for cert in certs:
            if cert.get("uid", "").lower() == uid_lower:
                return cert
        # Partial match fallback
        code = self._exam_uid_to_code(uid)
        for cert in certs:
            if code in cert.get("uid", "").lower() or code in cert.get("title", "").lower():
                return cert
        return None

    async def get_exams(self) -> list[dict[str, Any]]:
        """Fetch all Microsoft certification exams.

        Note: Not all exams appear here (e.g. AZ-900 is absent).
        Fall back to learning paths when an exam is not found.
        """
        data = await self._get(params={"type": "exams"})
        exams = data.get("exams", [])
        logger.info("Fetched %d exams", len(exams))
        return exams

    async def get_learning_paths(self) -> list[dict[str, Any]]:
        """Fetch all Microsoft Learn learning paths.

        Each path has: uid, title, url, levels, roles, products, modules
        (list of module UIDs), summary, duration_in_minutes.
        """
        data = await self._get(params={"type": "learningPaths"})
        paths = data.get("learningPaths", [])
        logger.info("Fetched %d learning paths", len(paths))
        return paths

    async def get_modules(self) -> list[dict[str, Any]]:
        """Fetch all Microsoft Learn modules.

        Each module has: uid, title, url, levels, roles, products,
        summary, duration_in_minutes, units (list of unit UIDs).
        """
        data = await self._get(params={"type": "modules"})
        modules = data.get("modules", [])
        logger.info("Fetched %d modules", len(modules))
        return modules

    async def get_learning_paths_for_exam(self, exam_uid: str) -> list[dict[str, Any]]:
        """Return learning paths relevant to an exam or certification UID.

        Searches path UIDs, titles, and product tags using aliases
        so that 'exam.az-900' or 'certification.azure-fundamentals'
        both return the AZ-900 learning paths.
        """
        terms = self._search_terms(exam_uid)
        all_paths = await self.get_learning_paths()
        matched: list[dict[str, Any]] = []
        for path in all_paths:
            path_text = " ".join([
                path.get("uid", ""),
                path.get("title", ""),
                " ".join(path.get("products", [])),
            ]).lower()
            if any(t in path_text for t in terms):
                matched.append(path)
        logger.info(
            "Found %d learning paths for exam %s (terms=%s)",
            len(matched), exam_uid, terms,
        )
        return matched

    async def get_modules_for_exam(self, exam_uid: str) -> list[dict[str, Any]]:
        """Fetch modules associated with a specific exam UID.

        Resolves via learning paths: finds paths for the exam, collects
        their module UIDs, then returns the matching module records.
        """
        # Step 1: find relevant learning paths
        relevant_paths = await self.get_learning_paths_for_exam(exam_uid)

        if not relevant_paths:
            logger.warning("No learning paths found for exam %s", exam_uid)
            return []

        # Step 2: collect module UIDs from those paths
        target_module_uids: set[str] = set()
        for path in relevant_paths:
            for mod_uid in path.get("modules", []):
                target_module_uids.add(mod_uid)

        if not target_module_uids:
            logger.warning("No module UIDs extracted for exam %s", exam_uid)
            return []

        # Step 3: fetch all modules and filter by uid
        all_modules = await self.get_modules()
        matched = [m for m in all_modules if m.get("uid") in target_module_uids]
        logger.info(
            "Found %d modules for exam %s (from %d paths)",
            len(matched), exam_uid, len(relevant_paths),
        )
        return matched
