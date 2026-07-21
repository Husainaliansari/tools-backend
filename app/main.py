"""Application entry point.

Defines the ``create_app()`` factory that assembles the FastAPI application from
its constituent layers — configuration, logging, middleware, exception handlers,
and routers — and exposes a module-level ``app`` for ASGI servers
(uvicorn/gunicorn) to import as ``app.main:app``.

The factory pattern keeps construction explicit and testable, and ensures the
same wiring is used everywhere (tests, dev server, production).
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api import api_router
from app.config import get_settings
from app.core.lifespan import lifespan
from app.exceptions import register_exception_handlers
from app.health import health_router
from app.logging import configure_logging
from app.middleware import register_middleware


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    settings = get_settings()

    # Configure logging before anything else so startup logs are formatted.
    configure_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.VERSION,
        docs_url=settings.DOCS_URL,
        redoc_url=settings.REDOC_URL,
        openapi_url=settings.OPENAPI_URL,
        debug=settings.DEBUG,
        lifespan=lifespan,
        contact={"name": "Engineering", "email": "engineering@example.com"},
        license_info={"name": "Proprietary"},
    )

    # Cross-cutting concerns.
    register_middleware(app, settings)
    register_exception_handlers(app)

    # Routers: operational endpoints first, then the versioned API.
    app.include_router(health_router)
    app.include_router(api_router)

    return app


app = create_app()
