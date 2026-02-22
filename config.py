"""CertBrain — Centralized configuration module.

Loads environment variables from .env, defines project-wide constants,
and sets up structured logging for the entire application.
"""

import logging
import sys
from pathlib import Path
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"


# ---------------------------------------------------------------------------
# Settings (loaded once via pydantic-settings)
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    """Application settings sourced from environment / .env file."""

    # Azure AI Foundry
    project_endpoint: str = Field(
        default="",
        description="Azure AI Foundry project endpoint",
    )
    model_deployment_name: str = Field(
        default="gpt-4o",
        description="Deployed model name in Azure AI Foundry",
    )

    # Microsoft Learn integrations (no auth required)
    catalog_api_base_url: str = "https://learn.microsoft.com/api/catalog/"
    mcp_server_url: str = "https://learn.microsoft.com/api/mcp"

    # Application defaults
    log_level: str = "INFO"
    default_locale: str = "en-us"
    mastery_pass_threshold: float = 0.80
    confidence_threshold: float = 0.70
    max_diagnostic_questions: int = 20
    spaced_repetition_initial_interval_days: int = 1

    model_config = {
        "env_file": str(ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
_LOG_FORMAT = "%(asctime)s | %(name)-28s | %(levelname)-7s | %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str | None = None) -> None:
    """Configure root logger for the CertBrain application.

    Parameters
    ----------
    level:
        Override log level (e.g. ``"DEBUG"``).  Falls back to
        ``Settings.log_level`` when *None*.
    """
    effective_level = (level or get_settings().log_level).upper()
    logging.basicConfig(
        level=getattr(logging, effective_level, logging.INFO),
        format=_LOG_FORMAT,
        datefmt=_LOG_DATE_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "azure", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger for *name* (typically ``__name__``)."""
    return logging.getLogger(f"certbrain.{name}")


# ---------------------------------------------------------------------------
# Convenience: run setup on first import so logging is always ready
# ---------------------------------------------------------------------------
setup_logging()
