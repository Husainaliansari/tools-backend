"""Production environment settings.

Hardened defaults: JSON logging, no SQL echo, docs endpoints kept enabled but
overridable, and validation that dangerous defaults are not shipped. All secrets
and hosts MUST be supplied through the environment.
"""

from __future__ import annotations

from pydantic import model_validator

from app.config.base import BaseAppSettings


class ProductionSettings(BaseAppSettings):
    """Overrides applied when ``APP_ENV=production``."""

    APP_ENV: str = "production"  # type: ignore[assignment]
    DEBUG: bool = False

    LOG_LEVEL: str = "INFO"
    LOG_RENDERER: str = "json"  # type: ignore[assignment]

    DB_ECHO: bool = False

    @model_validator(mode="after")
    def _enforce_production_hardening(self) -> ProductionSettings:
        """Fail fast on insecure production configuration."""
        if self.SECRET_KEY.startswith("change-me"):
            raise ValueError(
                "SECRET_KEY must be set to a strong, unique value in production."
            )
        if "*" in self.ALLOWED_HOSTS:
            raise ValueError(
                "ALLOWED_HOSTS must be an explicit allow-list in production "
                "(wildcard '*' is not permitted)."
            )
        return self
