"""Data access for processing jobs (async API side + sync worker side)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.constants import JobStatus
from app.models.job import JobFile, ProcessingJob
from app.repositories.base import BaseRepository


class JobRepository(BaseRepository[ProcessingJob]):
    """Async repository used by API request handlers."""

    model = ProcessingJob

    async def get_with_files(
        self,
        job_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
        any_owner: bool = False,
    ) -> ProcessingJob | None:
        query = (
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .options(selectinload(ProcessingJob.files).joinedload(JobFile.file))
        )
        if not any_owner:
            query = query.where(ProcessingJob.user_id.is_not_distinct_from(user_id))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[ProcessingJob]:
        result = await self.session.execute(
            select(ProcessingJob)
            .where(ProcessingJob.user_id == user_id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(limit)
            .offset(offset)
            .options(selectinload(ProcessingJob.files).joinedload(JobFile.file))
        )
        return list(result.scalars().unique().all())


class SyncJobRepository:
    """Sync repository used inside Celery worker tasks."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, job_id: uuid.UUID) -> ProcessingJob | None:
        return self.session.get(ProcessingJob, job_id)

    def get_with_files(self, job_id: uuid.UUID) -> ProcessingJob | None:
        result = self.session.execute(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .options(selectinload(ProcessingJob.files).joinedload(JobFile.file))
        )
        return result.unique().scalar_one_or_none()

    def set_progress(self, job: ProcessingJob, progress: int) -> None:
        job.progress = max(0, min(100, progress))

    def mark_processing(self, job: ProcessingJob) -> None:
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now(UTC)
        job.progress = 0

    def mark_completed(self, job: ProcessingJob) -> None:
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.finished_at = datetime.now(UTC)

    def mark_failed(
        self, job: ProcessingJob, *, error_code: str, error_message: str
    ) -> None:
        job.status = JobStatus.FAILED
        job.error_code = error_code
        # Never persist unbounded tool output.
        job.error_message = error_message[:2000]
        job.finished_at = datetime.now(UTC)

    def list_expired(self, *, now: datetime | None = None) -> list[ProcessingJob]:
        """Terminal jobs whose retention window has passed."""
        now = now or datetime.now(UTC)
        result = self.session.execute(
            select(ProcessingJob).where(
                ProcessingJob.status.in_(
                    [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]
                ),
                ProcessingJob.expires_at.is_not(None),
                ProcessingJob.expires_at < now,
            )
        )
        return list(result.scalars().all())
