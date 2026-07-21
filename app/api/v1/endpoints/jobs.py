"""Processing status endpoints.

One generic status API serves every tool: clients poll ``GET /jobs/{id}``,
subscribe to ``/jobs/{id}/ws`` (WebSocket push) or ``/jobs/{id}/events``
(SSE), then either follow each output file's ``download_url`` or fetch
everything at once via ``GET /jobs/{id}/download``.

Ownership: status/download respect the caller's identity. The ws/events
streams expose only status+progress and are addressed by unguessable job ID
(browser EventSource/WebSocket cannot send Authorization headers).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

from app.constants import JobStatus
from app.core.context import get_request_id
from app.db.redis import get_redis
from app.db.session import SessionFactory
from app.dependencies.auth import CurrentUserDep, OptionalUserIdDep
from app.dependencies.services import DownloadServiceDep, JobServiceDep
from app.logging import get_logger
from app.repositories.job import JobRepository
from app.schemas.job import JobInfo
from app.schemas.response import SuccessResponse
from app.services.job_events import job_channel

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs"])

# Streaming cadence and safety caps (~10 minutes).
_POLL_SECONDS = 1.0
_MAX_EVENTS = 600


async def _job_snapshot(job_id: uuid.UUID) -> dict | None:
    """Read the job's progress fields with a short-lived session."""
    async with SessionFactory() as session:
        job = await JobRepository(session).get(job_id)
        if job is None:
            return None
        return {
            "id": str(job.id),
            "status": str(job.status),
            "progress": job.progress,
            "error_code": job.error_code,
            "terminal": JobStatus(job.status).is_terminal,
        }


@router.get(
    "",
    response_model=SuccessResponse[list[JobInfo]],
    summary="List my jobs (requires authentication)",
)
async def list_jobs(
    user: CurrentUserDep,
    service: JobServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SuccessResponse[list[JobInfo]]:
    jobs = await service.jobs.list_for_user(user.id, limit=limit, offset=offset)
    return SuccessResponse(
        data=[JobInfo.from_model(job) for job in jobs],
        request_id=get_request_id(),
    )


@router.get(
    "/{job_id}",
    response_model=SuccessResponse[JobInfo],
    summary="Get processing job status and results",
)
async def get_job_status(
    job_id: uuid.UUID,
    service: JobServiceDep,
    user_id: OptionalUserIdDep,
) -> SuccessResponse[JobInfo]:
    job = await service.get_job(job_id, user_id=user_id)
    return SuccessResponse(data=JobInfo.from_model(job), request_id=get_request_id())


@router.get(
    "/{job_id}/download",
    response_class=FileResponse,
    summary="Download a completed job's results",
    description=(
        "Single output: the file itself. Multiple outputs: a ZIP archive "
        "containing all of them."
    ),
)
async def download_job_results(
    job_id: uuid.UUID,
    jobs: JobServiceDep,
    downloads: DownloadServiceDep,
    user_id: OptionalUserIdDep,
) -> FileResponse:
    job = await jobs.get_job(job_id, user_id=user_id)
    return await downloads.build_job_response(job)


@router.websocket("/{job_id}/ws")
async def job_progress_websocket(websocket: WebSocket, job_id: uuid.UUID) -> None:
    """Push job progress over WebSocket.

    True push: subscribes to the worker's Redis pub/sub channel and forwards
    events as they happen. Degrades to 1s DB polling when Redis is
    unavailable. Closes after the terminal event.
    """
    await websocket.accept()

    pubsub = None
    try:
        pubsub = get_redis().pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(job_channel(str(job_id)))
    except Exception:
        pubsub = None  # Redis down — poll only

    try:
        # Initial snapshot (also covers jobs that finished long ago).
        snapshot = await _job_snapshot(job_id)
        if snapshot is None:
            await websocket.send_json({"error": "JOB_NOT_FOUND"})
            return
        terminal = snapshot.pop("terminal")
        await websocket.send_json(snapshot)
        if terminal:
            return

        for _ in range(_MAX_EVENTS):
            pushed = None
            if pubsub is not None:
                try:
                    message = await pubsub.get_message(timeout=_POLL_SECONDS)
                    if message and message.get("type") == "message":
                        pushed = json.loads(message["data"])
                except Exception:
                    pubsub = None  # degrade to polling mid-stream

            if pushed is not None:
                await websocket.send_json(pushed)
                if JobStatus(pushed["status"]).is_terminal:
                    return
                continue

            if pubsub is None:
                await asyncio.sleep(_POLL_SECONDS)
            snapshot = await _job_snapshot(job_id)
            if snapshot is None:
                await websocket.send_json({"error": "JOB_NOT_FOUND"})
                return
            terminal = snapshot.pop("terminal")
            await websocket.send_json(snapshot)
            if terminal:
                return
    except WebSocketDisconnect:
        pass
    finally:
        if pubsub is not None:
            with contextlib.suppress(Exception):
                await pubsub.close()
        with contextlib.suppress(Exception):  # may already be closed
            await websocket.close()


@router.get(
    "/{job_id}/events",
    summary="Stream job progress as Server-Sent Events",
    description=(
        "Emits an SSE `data:` event with {status, progress, error} roughly "
        "once per second until the job reaches a terminal state. Fallback "
        "for clients that cannot use the WebSocket endpoint."
    ),
)
async def stream_job_events(job_id: uuid.UUID) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        for _ in range(_MAX_EVENTS):
            snapshot = await _job_snapshot(job_id)
            if snapshot is None:
                yield 'event: error\ndata: {"code": "JOB_NOT_FOUND"}\n\n'
                return
            terminal = snapshot.pop("terminal")
            yield f"data: {json.dumps(snapshot)}\n\n"
            if terminal:
                return
            await asyncio.sleep(_POLL_SECONDS)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
