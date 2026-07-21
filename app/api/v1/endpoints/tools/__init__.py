"""Tool endpoint modules plus the shared router factory.

Every tool exposes the identical HTTP shape::

    POST /api/v1/tools/<slug>   {file_ids: [...], options: {...}}  ->  202 JobInfo

so the router is generated from the tool's service class instead of being
re-written per tool. A tool module is one line::

    router = create_tool_router(PptToPdfService)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_request_id
from app.db import get_db
from app.dependencies.auth import OptionalUserDep
from app.schemas.job import JobCreateRequest, JobInfo
from app.schemas.response import SuccessResponse
from app.services.jobs import JobService
from app.services.tool_base import BaseToolService

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def create_tool_router(service_cls: type[BaseToolService]) -> APIRouter:
    """Build the standard job-creation router for one tool service."""
    slug = service_cls.slug.value
    router = APIRouter(prefix=f"/tools/{slug}", tags=["Tools"])

    @router.post(
        "",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=SuccessResponse[JobInfo],
        summary=f"Run the '{slug}' tool",
        description=(
            f"Create a '{slug}' processing job from previously uploaded files. "
            "Poll GET /jobs/{job_id} for progress and results."
        ),
        name=f"tools_{slug.replace('-', '_')}_create_job",
    )
    async def create_job(
        payload: JobCreateRequest,
        session: SessionDep,
        user: OptionalUserDep,
    ) -> SuccessResponse[JobInfo]:
        user_id = user.id if user else None
        service = service_cls(session)
        job = await service.create_job(
            payload.file_ids,
            payload.options,
            user_id=user_id,
            plan=user.plan if user else None,
        )
        # Re-read with file links so the response carries input metadata
        # (and, under eager test execution, the final status).
        job = await JobService(session).get_job(job.id, user_id=user_id)
        return SuccessResponse(
            data=JobInfo.from_model(job),
            message="Job accepted.",
            request_id=get_request_id(),
        )

    return router
