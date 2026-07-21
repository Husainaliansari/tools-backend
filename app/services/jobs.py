"""Job query service (Processing Status API backing).

Read-side operations on processing jobs. Job *creation* goes through the tool
services (see ``tool_base.py``); this service is what the generic status and
result endpoints use.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.jobs import JobNotFoundError
from app.models.job import ProcessingJob
from app.repositories.job import JobRepository


class JobService:
    """Lookups for the processing status endpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self.jobs = JobRepository(session)

    async def get_job(
        self, job_id: uuid.UUID, *, user_id: uuid.UUID | None = None
    ) -> ProcessingJob:
        job = await self.jobs.get_with_files(job_id, user_id=user_id)
        if job is None:
            raise JobNotFoundError()
        return job
