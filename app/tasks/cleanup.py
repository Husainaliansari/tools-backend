"""Cleanup scheduler tasks (Celery Beat).

Runs periodically to keep disk usage bounded:

* deletes expired files from disk and marks their rows ``expired``,
* marks terminal jobs past their retention window ``expired``,
* purges orphaned temp workspaces left behind by crashed workers.

The schedule is registered in ``app/workers/celery_app.py``.
"""

from __future__ import annotations

from celery import shared_task

from app.constants import FileStatus, JobStatus
from app.db.sync_session import sync_session
from app.logging import get_logger
from app.repositories.file import SyncFileRepository
from app.repositories.job import SyncJobRepository
from app.services.storage import get_storage
from app.services.temp_files import purge_stale_workspaces

logger = get_logger(__name__)


@shared_task(name="maintenance.cleanup_expired")
def cleanup_expired() -> dict[str, int]:
    """Purge expired files, expired jobs and stale temp workspaces."""
    storage = get_storage()
    files_removed = 0
    jobs_expired = 0

    with sync_session() as session:
        file_repo = SyncFileRepository(session)
        for record in file_repo.list_expired():
            storage.delete(record.category, record.relative_path)
            record.status = FileStatus.EXPIRED
            files_removed += 1

        job_repo = SyncJobRepository(session)
        for job in job_repo.list_expired():
            job.status = JobStatus.EXPIRED
            jobs_expired += 1

    temp_removed = purge_stale_workspaces()

    summary = {
        "files_removed": files_removed,
        "jobs_expired": jobs_expired,
        "temp_workspaces_removed": temp_removed,
    }
    logger.info("cleanup_finished", **summary)
    return summary
