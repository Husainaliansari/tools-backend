"""Application lifespan management.

Uses FastAPI's lifespan protocol to run startup/shutdown logic exactly once per
process. On startup we log a structured banner; on shutdown we gracefully
release pooled resources (database engine, Redis pool). Feature-specific warmups
(caches, clients) are added here as the app grows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db.redis import close_redis
from app.db.session import dispose_engine
from app.logging import get_logger
from app.services.storage import get_storage

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown."""
    settings = get_settings()

    # Guarantee the local storage tree exists before any request needs it.
    get_storage().ensure_structure()

    # Ensure the admin panel's baseline data (admin account, tool configs,
    # default settings) exists. Idempotent and best-effort.
    from app.services.admin_bootstrap import bootstrap_admin

    await bootstrap_admin()

    # Eager-Celery deployments run conversions inside this process, so the
    # LibreOffice warm-up belongs here (workers do it via worker_ready).
    if settings.CELERY_TASK_ALWAYS_EAGER:
        from app.utils.office import prewarm_office_runtime

        prewarm_office_runtime()

    logger.info(
        "application_startup",
        project=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.APP_ENV,
        storage_root=str(settings.storage_root_resolved),
    )

    try:
        yield
    finally:
        logger.info("application_shutdown")
        await dispose_engine()
        await close_redis()
