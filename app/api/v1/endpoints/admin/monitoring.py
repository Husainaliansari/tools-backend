"""Admin monitoring endpoints: performance, live activity, error & audit logs."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.endpoints.admin._common import PageParamsDep, ok, paged
from app.common.pagination import Page
from app.dependencies.admin import AdminUserDep
from app.dependencies.services import AdminServiceDep
from app.schemas.admin import AuditLogRow, ErrorLogRow
from app.schemas.response import SuccessResponse

router = APIRouter(tags=["Admin: Monitoring"])


@router.get("/monitoring/performance", response_model=SuccessResponse[dict])
async def performance(service: AdminServiceDep) -> SuccessResponse[dict]:
    return ok(await service.performance())


@router.get("/monitoring/live", response_model=SuccessResponse[dict])
async def live(service: AdminServiceDep) -> SuccessResponse[dict]:
    return ok(await service.live_activity())


# ── Audit logs (audit + security views) ──────────────────────────────────
@router.get("/audit", response_model=SuccessResponse[Page[AuditLogRow]])
async def list_audit(
    service: AdminServiceDep,
    params: PageParamsDep,
    category: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[AuditLogRow]]:
    rows, total = await service.list_audit(page=params, category=category, q=q)
    return paged([AuditLogRow.model_validate(r) for r in rows], total, params)


# ── Error logs ───────────────────────────────────────────────────────────
@router.get("/errors", response_model=SuccessResponse[Page[ErrorLogRow]])
async def list_errors(
    service: AdminServiceDep,
    params: PageParamsDep,
    level: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[ErrorLogRow]]:
    rows, total = await service.list_errors(page=params, level=level, q=q)
    return paged([ErrorLogRow.model_validate(r) for r in rows], total, params)


@router.post("/errors/{err_id}/resolve", response_model=SuccessResponse[ErrorLogRow])
async def resolve_error(
    err_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[ErrorLogRow]:
    err = await service.resolve_error(err_id, True)
    await service.audit(
        actor=admin, action="error.resolve", summary="Resolved error",
        category="security", entity_type="error", entity_id=str(err_id),
    )
    return ok(ErrorLogRow.model_validate(err))


@router.delete("/errors/{err_id}", response_model=SuccessResponse[None])
async def delete_error(
    err_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[None]:
    await service.delete_error(err_id)
    await service.audit(
        actor=admin, action="error.delete", summary="Deleted error log",
        category="security", entity_type="error", entity_id=str(err_id),
    )
    return ok(None, "Error log deleted.")


@router.post("/errors/clear-resolved", response_model=SuccessResponse[dict])
async def clear_resolved(
    service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[dict]:
    count = await service.clear_resolved_errors()
    await service.audit(
        actor=admin, action="error.clear_resolved",
        summary=f"Cleared {count} resolved error(s)", category="security",
    )
    return ok({"cleared": count}, f"Cleared {count} resolved error(s).")
