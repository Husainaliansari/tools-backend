"""Top-level API router.

Aggregates all versioned API routers under their version prefix. The
application factory mounts this single router, keeping ``main.py`` free of
per-feature wiring.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.v1.router import api_v1_router
from app.config import get_settings

settings = get_settings()

api_router = APIRouter()
# Auth is unversioned (mounted at /api/auth) to match the frontend contract.
api_router.include_router(auth_router)
api_router.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)
