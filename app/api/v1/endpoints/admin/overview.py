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
async def analytics(
    service: AdminServiceDep,
    start_date: str | None = None,
    end_date: str | None = None,
    device: str | None = None,
    browser: str | None = None,
    country: str | None = None,
    source: str | None = None,
    visitor_type: str | None = "total",
    group_by: str | None = "daily",
) -> SuccessResponse[dict[str, Any]]:
    return ok(
        await service.analytics(
            start_date=start_date,
            end_date=end_date,
            device=device,
            browser=browser,
            country=country,
            source=source,
            visitor_type=visitor_type,
            group_by=group_by,
        )
    )


@router.get("/analytics/tools", response_model=SuccessResponse[dict])
async def tool_analytics(
    service: AdminServiceDep,
    start_date: str | None = None,
    end_date: str | None = None,
    device: str | None = None,
    browser: str | None = None,
    country: str | None = None,
    source: str | None = None,
    visitor_type: str | None = "total",
    group_by: str | None = "daily",
) -> SuccessResponse[dict[str, Any]]:
    return ok(
        await service.tool_analytics(
            start_date=start_date,
            end_date=end_date,
            device=device,
            browser=browser,
            country=country,
            source=source,
            visitor_type=visitor_type,
            group_by=group_by,
        )
    )
