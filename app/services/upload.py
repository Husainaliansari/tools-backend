"""File upload service.

Accepts a batch of multipart uploads, validates each (count, type via magic
bytes, per-file and combined size while streaming — all capped by the
caller's subscription plan), persists them into ``uploads/`` and records a
:class:`StoredFile` row per file. The whole batch is atomic: if any file
fails, previously-written files of the batch are removed from disk and no
rows are committed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.config.plans import PlanLimits, limits_for_plan
from app.constants import FileCategory, FileStatus
from app.exceptions.files import FileTooLargeError
from app.logging import get_logger
from app.models.file import StoredFile
from app.repositories.file import FileRepository
from app.services.file_validation import (
    SNIFF_SIZE,
    validate_file_count,
    validate_file_type,
)
from app.services.storage import LocalStorageService, get_storage
from app.utils.filenames import sanitize_filename

logger = get_logger(__name__)


class UploadService:
    """Handles multi-file uploads end to end."""

    def __init__(
        self,
        session: AsyncSession,
        storage: LocalStorageService | None = None,
    ) -> None:
        self.session = session
        self.files = FileRepository(session)
        self.storage = storage or get_storage()
        self._settings = get_settings()

    async def upload_files(
        self,
        uploads: list[UploadFile],
        *,
        allowed_extensions: set[str] | None = None,
        user_id: uuid.UUID | None = None,
        plan: str | None = None,
    ) -> list[StoredFile]:
        """Validate and persist a batch of uploads. Atomic per batch.

        ``plan`` selects the caller's subscription limits (file count,
        per-file size, combined batch size); anonymous uploads get the
        free tier.
        """
        limits = limits_for_plan(plan)
        validate_file_count(len(uploads), max_files=limits.max_files)

        expires_at = datetime.now(UTC) + timedelta(
            hours=self._settings.FILE_RETENTION_HOURS
        )
        stored: list[StoredFile] = []
        written_paths = []
        # The batch budget shrinks as files land; a file may never exceed
        # min(per-file cap, what's left of the batch), so both limits are
        # enforced while streaming — declared sizes are never trusted.
        remaining_total = limits.max_total_size_bytes

        try:
            for upload in uploads:
                record = await self._store_one(
                    upload,
                    allowed_extensions=allowed_extensions,
                    expires_at=expires_at,
                    user_id=user_id,
                    max_bytes=min(limits.max_file_size_bytes, remaining_total),
                    limits=limits,
                    total_is_binding=remaining_total < limits.max_file_size_bytes,
                )
                stored.append(record)
                written_paths.append((record.category, record.relative_path))
                remaining_total -= record.size_bytes
            await self.session.commit()
        except Exception:
            # Roll back both the transaction and any bytes already on disk.
            await self.session.rollback()
            for category, relative_path in written_paths:
                self.storage.delete(category, relative_path)
            raise

        logger.info(
            "files_uploaded",
            count=len(stored),
            total_bytes=sum(f.size_bytes for f in stored),
        )
        return stored

    async def _store_one(
        self,
        upload: UploadFile,
        *,
        allowed_extensions: set[str] | None,
        expires_at: datetime,
        user_id: uuid.UUID | None,
        max_bytes: int,
        limits: PlanLimits,
        total_is_binding: bool,
    ) -> StoredFile:
        original_name = sanitize_filename(upload.filename or "file")

        # Sniff leading bytes before writing anything to disk.
        head = await upload.read(SNIFF_SIZE)
        spec = validate_file_type(
            original_name, head, allowed_extensions=allowed_extensions
        )

        allocated = self.storage.allocate(FileCategory.UPLOAD, spec.extension)
        # Size cap and checksum are both handled while streaming — the file
        # is never read back.
        try:
            size, checksum = await self.storage.write_stream(
                upload,
                allocated.absolute_path,
                max_bytes=max_bytes,
                first_chunk=head,
            )
        except FileTooLargeError:
            if total_is_binding:
                raise FileTooLargeError(
                    f"Adding '{original_name}' exceeds the "
                    f"{limits.max_total_size_mb} MB combined upload limit of "
                    f"the {limits.label} plan."
                ) from None
            raise FileTooLargeError(
                f"'{original_name}' exceeds the {limits.max_file_size_mb} MB "
                f"per-file limit of the {limits.label} plan."
            ) from None

        record = StoredFile(
            original_name=original_name,
            stored_name=allocated.stored_name,
            category=FileCategory.UPLOAD,
            relative_path=allocated.relative_path,
            media_type=spec.media_type,
            extension=spec.extension,
            size_bytes=size,
            checksum_sha256=checksum,
            status=FileStatus.ACTIVE,
            expires_at=expires_at,
            user_id=user_id,
        )
        self.files.add(record)
        await self.files.flush()
        return record
