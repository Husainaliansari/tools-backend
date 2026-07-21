"""Configuration package.

Exposes a single cached ``get_settings()`` factory that selects the correct
settings class based on the ``APP_ENV`` environment variable. Import the
settings anywhere via::

    from app.config import get_settings

    settings = get_settings()

The result is memoised so settings are parsed exactly once per process.
"""

from __future__ import annotations

import os
from functools import lru_cache

from app.config.base import BaseAppSettings
from app.config.development import DevelopmentSettings
from app.config.production import ProductionSettings

__all__ = ["BaseAppSettings", "Settings", "get_settings"]

# Public alias for type hints elsewhere in the codebase.
Settings = BaseAppSettings

_ENV_TO_SETTINGS: dict[str, type[BaseAppSettings]] = {
    "development": DevelopmentSettings,
    "production": ProductionSettings,
    # "staging"/"testing" fall back to base + env overrides by default.
}


@lru_cache
def get_settings() -> BaseAppSettings:
    """Return the memoised settings instance for the current environment."""
    env = os.getenv("APP_ENV", "development").lower()
    settings_cls = _ENV_TO_SETTINGS.get(env, BaseAppSettings)
    return settings_cls()
