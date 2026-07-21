"""Development environment settings.

Optimised for developer ergonomics: verbose logging, human-readable log output,
SQL echo, and permissive CORS. These values are safe for local machines only.
"""

from __future__ import annotations

from pydantic import Field

from app.config.base import BaseAppSettings


class DevelopmentSettings(BaseAppSettings):
    """Overrides applied when ``APP_ENV=development``."""

    APP_ENV: str = "development"  # type: ignore[assignment]
    DEBUG: bool = True

    # Human-friendly, coloured console logs during development.
    LOG_LEVEL: str = "DEBUG"
    LOG_RENDERER: str = "console"  # type: ignore[assignment]

    # Echo SQL statements to aid debugging.
    DB_ECHO: bool = True

    # Permissive local defaults. Never used in production.
    ALLOWED_HOSTS: list[str] = Field(default_factory=lambda: ["*"])
