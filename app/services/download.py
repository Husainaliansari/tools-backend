"""File download service.

Resolves a stored file to a streamable response, enforcing lifecycle rules
(must exist, must be active, must not be past its expiry) so every download
endpoint behaves identically regardless of which tool produced the file.

Also provides bundled downloads: a job's outputs (single file direct,
several as ZIP) and ad-hoc archives of arbitrary owned files — used by the
frontend's "Download all" when results span several per-file jobs. ZIPs are
built in ``temp/`` and removed after the response is sent.
"""

from __future__ import annotations

import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import anyio
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.config import get_settings
from app.constants import JobFileRole, JobStatus, ToolSlug
from app.exceptions.files import FileExpiredError, FileNotFoundAppError
from app.exceptions.jobs import JobNotCompletedError
from app.models.file import StoredFile
from app.models.job import ProcessingJob
from app.repositories.file import FileRepository
from app.services.storage import LocalStorageService, get_storage


def archive_download_name(tool: str | None, count: int) -> str:
    """Name for a multi-file ZIP download: tool + file count + date.

    e.g. ``ppt-to-pdf-5-files-2026-07-09.zip``. ``tool`` is only trusted
    when it names a known tool slug — the frontend sends it as a query
    parameter, so it is user input headed for a response header; anything
    unrecognised falls back to a generic prefix.
    """
    try:
        prefix = ToolSlug(tool).value if tool else "converted"
    except ValueError:
        prefix = "converted"
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"{prefix}-{count}-files-{stamp}.zip"


class DownloadService:
    """Turns StoredFile rows into HTTP file responses."""

    def __init__(
        self,
        session: AsyncSession,
        storage: LocalStorageService | None = None,
    ) -> None:
        self.files = FileRepository(session)
        self.storage = storage or get_storage()

    async def get_downloadable(
        self, file_id: uuid.UUID, *, user_id: uuid.UUID | None = None
    ) -> tuple[StoredFile, Path]:
        """Fetch a file and its on-disk path, enforcing lifecycle + ownership."""
        record = await self.files.get_active(file_id, user_id=user_id)
        if record is None:
            raise FileNotFoundAppError()
        if record.expires_at is not None and record.expires_at < datetime.now(UTC):
            raise FileExpiredError()

        path = self.storage.resolve(record.category, record.relative_path)
        if not path.is_file():
            # Row says active but bytes are gone — treat as expired, not a 500.
            raise FileExpiredError()
        return record, path

    async def build_response(
        self, file_id: uuid.UUID, *, user_id: uuid.UUID | None = None
    ) -> FileResponse:
        record, path = await self.get_downloadable(file_id, user_id=user_id)
        return FileResponse(
            path=path,
            media_type=record.media_type,
            filename=record.original_name,
            content_disposition_type="attachment",
        )

    # ------------------------------------------------------------------ #
    # Job-level download (single file direct, multiple files as ZIP)
    # ------------------------------------------------------------------ #
    async def build_job_response(self, job: ProcessingJob) -> FileResponse:
        """Serve a completed job's outputs: one file directly, several as ZIP."""
        if job.status != JobStatus.COMPLETED:
            raise JobNotCompletedError()

        output_links = sorted(
            (link for link in job.files if link.role == JobFileRole.OUTPUT),
            key=lambda link: link.position,
        )
        if not output_links:
            raise JobNotCompletedError("The job has no downloadable results.")

        if len(output_links) == 1:
            # Ownership was already checked on the job; outputs share its owner.
            return await self.build_response(
                output_links[0].file_id, user_id=job.user_id
            )

        entries: list[tuple[Path, str]] = []
        for link in output_links:
            record = link.file
            path = self.storage.resolve(record.category, record.relative_path)
            if not path.is_file():
                raise FileExpiredError()
            entries.append((path, record.original_name))

        return await self._build_zip_response(
            entries,
            download_name=archive_download_name(job.tool, len(output_links)),
        )

    async def build_archive_response(
        self,
        file_ids: list[uuid.UUID],
        *,
        user_id: uuid.UUID | None = None,
        download_name: str = "files.zip",
    ) -> FileResponse:
        """Bundle several owned files into one ZIP download.

        Serves the frontend's "Download all" when a batch run produced its
        results across independent per-file jobs (so no single job owns them).
        A single file is served directly, mirroring the job-level download.
        """
        if len(file_ids) == 1:
            return await self.build_response(file_ids[0], user_id=user_id)

        entries: list[tuple[Path, str]] = []
        for file_id in file_ids:
            record, path = await self.get_downloadable(file_id, user_id=user_id)
            entries.append((path, record.original_name))
        return await self._build_zip_response(entries, download_name=download_name)

    async def _build_zip_response(
        self, entries: list[tuple[Path, str]], *, download_name: str
    ) -> FileResponse:
        """ZIP the given (path, archive name) entries into a one-shot download."""
        deduped: list[tuple[Path, str]] = []
        used_names: set[str] = set()
        for path, original_name in entries:
            arcname = original_name
            counter = 1
            while arcname in used_names:  # duplicate download names
                stem, dot, suffix = original_name.rpartition(".")
                arcname = (
                    f"{stem} ({counter}).{suffix}"
                    if dot
                    else f"{original_name} ({counter})"
                )
                counter += 1
            used_names.add(arcname)
            deduped.append((path, arcname))

        settings = get_settings()
        zip_path = settings.TEMP_DIR / f"bundle-{uuid.uuid4().hex}.zip"

        def _build_zip() -> None:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for path, arcname in deduped:
                    archive.write(path, arcname)

        # Zipping is CPU/disk bound — keep it off the event loop.
        await anyio.to_thread.run_sync(_build_zip)

        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=download_name,
            content_disposition_type="attachment",
            background=BackgroundTask(zip_path.unlink, missing_ok=True),
        )
