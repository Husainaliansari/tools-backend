"""Admin dashboard + analytics endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.v1.endpoints.admin._common import ok
from app.dependencies.services import AdminServiceDep
from app.schemas.response import SuccessResponse

router = APIRouter(tags=["Admin"])


@router.get("/overview", response_model=SuccessResponse[dict])
async def overview(service: AdminServiceDep) -> SuccessResponse[dict[str, Any]]:
    return ok(await service.overview())


@router.get("/analytics", response_model=SuccessResponse[dict])
async def analytics(service: AdminServiceDep) -> SuccessResponse[dict[str, Any]]:
    return ok(await service.analytics())
