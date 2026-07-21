"""Job API schemas (shared by every tool's endpoints)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.constants import JobFileRole, JobStatus
from app.models.job import ProcessingJob
from app.schemas.base import BaseSchema, ORMSchema
from app.schemas.file import FileInfo


class JobCreateRequest(BaseSchema):
    """Generic job-creation payload: input files + tool-specific options.

    Tool endpoints accept this shape; the tool's ``options_model`` validates
    the ``options`` dict before anything is enqueued.
    """

    file_ids: list[uuid.UUID] = Field(..., min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


class JobError(BaseSchema):
    code: str
    message: str


class JobInfo(ORMSchema):
    """Public representation of a processing job (Processing Status API)."""

    id: uuid.UUID
    tool: str
    status: JobStatus
    progress: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    expires_at: datetime | None = None
    error: JobError | None = None
    input_files: list[FileInfo] = Field(default_factory=list)
    output_files: list[FileInfo] = Field(default_factory=list)

    @classmethod
    def from_model(cls, job: ProcessingJob) -> JobInfo:
        inputs = [
            FileInfo.from_model(link.file)
            for link in job.files
            if link.role == JobFileRole.INPUT
        ]
        outputs = [
            FileInfo.from_model(link.file)
            for link in job.files
            if link.role == JobFileRole.OUTPUT
        ]
        error = (
            JobError(code=job.error_code, message=job.error_message or "")
            if job.error_code
            else None
        )
        return cls(
            id=job.id,
            tool=job.tool,
            status=job.status,
            progress=job.progress,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            expires_at=job.expires_at,
            error=error,
            input_files=inputs,
            output_files=outputs,
        )
