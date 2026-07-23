"""Admin files & conversion-jobs endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.endpoints.admin._common import PageParamsDep, ok, paged
from app.common.pagination import Page
from app.dependencies.admin import AdminUserDep
from app.dependencies.services import AdminServiceDep
from app.schemas.admin import AdminFileRow, AdminJobRow
from app.schemas.response import SuccessResponse

router = APIRouter(tags=["Admin: Storage"])


# ── Files ────────────────────────────────────────────────────────────────
@router.get("/files", response_model=SuccessResponse[Page[AdminFileRow]])
async def list_files(
    service: AdminServiceDep,
    params: PageParamsDep,
    q: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    sort: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[AdminFileRow]]:
    rows, total = await service.list_files(
        page=params, q=q, category=category, sort=sort
    )
    return paged([AdminFileRow(**r) for r in rows], total, params)


@router.get("/files/stats", response_model=SuccessResponse[dict])
async def file_stats(service: AdminServiceDep) -> SuccessResponse[dict]:
    return ok(await service.file_stats())


@router.delete("/files/{file_id}", response_model=SuccessResponse[None])
async def delete_file(
    file_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[None]:
    await service.delete_file(file_id)
    await service.audit(
        actor=admin,
        action="file.delete",
        summary="Deleted file",
        entity_type="file",
        entity_id=str(file_id),
    )
    return ok(None, "File deleted.")


@router.post("/files/purge-temp", response_model=SuccessResponse[dict])
async def purge_temp(
    service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[dict]:
    count = await service.purge_expired_files()
    await service.audit(
        actor=admin,
        action="file.purge",
        summary=f"Purged {count} expired file(s)",
    )
    return ok({"purged": count}, f"Purged {count} expired file(s).")


# ── Jobs ─────────────────────────────────────────────────────────────────
@router.get("/jobs", response_model=SuccessResponse[Page[AdminJobRow]])
async def list_jobs(
    service: AdminServiceDep,
    params: PageParamsDep,
    q: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    sort: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[AdminJobRow]]:
    rows, total = await service.list_jobs(page=params, q=q, status=status, sort=sort)
    return paged([AdminJobRow(**r) for r in rows], total, params)


@router.get("/jobs/stats", response_model=SuccessResponse[dict])
async def job_stats(service: AdminServiceDep) -> SuccessResponse[dict]:
    return ok(await service.job_stats())


@router.post("/jobs/{job_id}/cancel", response_model=SuccessResponse[AdminJobRow])
async def cancel_job(
    job_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[AdminJobRow]:
    job = await service.cancel_job(job_id)
    await service.audit(
        actor=admin,
        action="job.cancel",
        summary=f"Cancelled job {job.tool}",
        entity_type="job",
        entity_id=str(job.id),
    )
    return ok(AdminJobRow(**service._job_row(job, None)))


@router.post("/jobs/{job_id}/retry", response_model=SuccessResponse[AdminJobRow])
async def retry_job(
    job_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[AdminJobRow]:
    job = await service.retry_job(job_id)
    await service.audit(
        actor=admin,
        action="job.retry",
        summary=f"Requeued job {job.tool}",
        entity_type="job",
        entity_id=str(job.id),
    )
    return ok(AdminJobRow(**service._job_row(job, None)))
