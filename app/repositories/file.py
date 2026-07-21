"""Data access for stored files (async API side + sync worker side)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import FileStatus
from app.models.file import StoredFile
from app.repositories.base import BaseRepository


class FileRepository(BaseRepository[StoredFile]):
    """Async repository used by API request handlers."""

    model = StoredFile

    async def get_active(
        self, file_id: uuid.UUID, *, user_id: uuid.UUID | None = None
    ) -> StoredFile | None:
        """Return the file only if it is still active and owned by the caller.

        Ownership rule: anonymous callers see anonymous files; authenticated
        callers see their own. (``user_id IS NOT DISTINCT FROM :caller``.)
        """
        result = await self.session.execute(
            select(StoredFile).where(
                StoredFile.id == file_id,
                StoredFile.status == FileStatus.ACTIVE,
                StoredFile.user_id.is_not_distinct_from(user_id),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[StoredFile]:
        result = await self.session.execute(
            select(StoredFile)
            .where(
                StoredFile.user_id == user_id,
                StoredFile.status == FileStatus.ACTIVE,
            )
            .order_by(StoredFile.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_many(self, file_ids: list[uuid.UUID]) -> list[StoredFile]:
        """Fetch several files at once, preserving the requested order."""
        result = await self.session.execute(
            select(StoredFile).where(StoredFile.id.in_(file_ids))
        )
        by_id = {f.id: f for f in result.scalars().all()}
        return [by_id[fid] for fid in file_ids if fid in by_id]


class SyncFileRepository:
    """Sync repository used inside Celery worker tasks."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, file_id: uuid.UUID) -> StoredFile | None:
        return self.session.get(StoredFile, file_id)

    def add(self, file: StoredFile) -> StoredFile:
        self.session.add(file)
        return file

    def list_expired(self, *, now: datetime | None = None) -> list[StoredFile]:
        """Files whose retention window has passed and that still hold disk space."""
        now = now or datetime.now(UTC)
        result = self.session.execute(
            select(StoredFile).where(
                StoredFile.status == FileStatus.ACTIVE,
                StoredFile.expires_at.is_not(None),
                StoredFile.expires_at < now,
            )
        )
        return list(result.scalars().all())
