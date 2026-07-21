"""Local filesystem storage service.

Owns the on-disk storage tree::

    <STORAGE_ROOT>/
        uploads/     YYYY/MM/DD/<uuid>.<ext>   (raw user uploads)
        processed/   YYYY/MM/DD/<uuid>.<ext>   (tool outputs)
        temp/        <workspace-id>/           (scratch space, see temp_files)
        thumbnails/  YYYY/MM/DD/<uuid>.<ext>
        logs/                                   (rotating app logs)

Files are addressed by ``(category, relative_path)`` as recorded on their
:class:`StoredFile` row; this service is the only code that turns that pair
into an absolute path, and it refuses to resolve paths that escape the tree.

Methods are synchronous filesystem primitives (cheap metadata ops or worker
usage); the streaming write used during uploads is async so the API event loop
is never blocked by disk I/O.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Protocol

import aiofiles

from app.config import get_settings
from app.constants import FileCategory
from app.exceptions.files import FileTooLargeError, StorageError
from app.logging import get_logger
from app.utils.filenames import generate_stored_name

logger = get_logger(__name__)


class AsyncByteReader(Protocol):
    """Anything with an async ``read(n)`` — e.g. Starlette's UploadFile."""

    async def read(self, size: int = -1, /) -> bytes: ...


@dataclass(frozen=True)
class AllocatedPath:
    """A reserved location in the storage tree for a new file."""

    stored_name: str
    relative_path: str
    absolute_path: Path


class LocalStorageService:
    """Filesystem operations for the storage tree."""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------ #
    # Structure
    # ------------------------------------------------------------------ #
    @property
    def root(self) -> Path:
        return self._settings.storage_root_resolved

    def category_root(self, category: FileCategory) -> Path:
        mapping = {
            FileCategory.UPLOAD: self._settings.UPLOADS_DIR,
            FileCategory.PROCESSED: self._settings.PROCESSED_DIR,
            FileCategory.THUMBNAIL: self._settings.THUMBNAILS_DIR,
        }
        return mapping[FileCategory(category)]

    def ensure_structure(self) -> None:
        """Create the full storage tree. Idempotent; called at startup."""
        for directory in (
            self._settings.UPLOADS_DIR,
            self._settings.PROCESSED_DIR,
            self._settings.TEMP_DIR,
            self._settings.THUMBNAILS_DIR,
            self._settings.LOGS_DIR,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        logger.debug("storage_structure_ensured", root=str(self.root))

    # ------------------------------------------------------------------ #
    # Path handling
    # ------------------------------------------------------------------ #
    def allocate(self, category: FileCategory, extension: str) -> AllocatedPath:
        """Reserve a date-sharded, UUID-named location for a new file."""
        stored_name = generate_stored_name(extension)
        today = datetime.now(UTC)
        relative = Path(f"{today:%Y/%m/%d}") / stored_name
        absolute = self.category_root(category) / relative
        absolute.parent.mkdir(parents=True, exist_ok=True)
        return AllocatedPath(
            stored_name=stored_name,
            relative_path=relative.as_posix(),
            absolute_path=absolute,
        )

    def resolve(self, category: FileCategory, relative_path: str) -> Path:
        """Turn a stored (category, relative_path) into a safe absolute path."""
        base = self.category_root(category)
        candidate = (base / relative_path).resolve()
        if not candidate.is_relative_to(base.resolve()):
            # A DB row should never contain a traversal path; treat as corruption.
            raise StorageError("Stored file path escapes the storage tree.")
        return candidate

    # ------------------------------------------------------------------ #
    # I/O
    # ------------------------------------------------------------------ #
    async def write_stream(
        self,
        source: AsyncByteReader,
        destination: Path,
        *,
        max_bytes: int,
        first_chunk: bytes = b"",
    ) -> tuple[int, str]:
        """Stream an upload to disk, enforcing the size cap as bytes arrive.

        ``first_chunk`` allows the caller to sniff magic bytes before deciding
        to persist, without re-reading the source. The SHA-256 checksum is
        computed on the fly (no second pass over the file). Returns
        ``(bytes_written, checksum)``; removes the partial file and raises if
        the cap is exceeded.
        """
        chunk_size = self._settings.UPLOAD_CHUNK_SIZE
        digest = hashlib.sha256()
        written = 0
        try:
            async with aiofiles.open(destination, "wb") as out:
                if first_chunk:
                    written += len(first_chunk)
                    if written > max_bytes:
                        raise FileTooLargeError()
                    digest.update(first_chunk)
                    await out.write(first_chunk)
                while chunk := await source.read(chunk_size):
                    written += len(chunk)
                    if written > max_bytes:
                        raise FileTooLargeError()
                    digest.update(chunk)
                    await out.write(chunk)
        except Exception:
            # Error path only; a single unlink is not worth a thread hop.
            destination.unlink(missing_ok=True)  # noqa: ASYNC240
            raise
        return written, digest.hexdigest()

    def import_file(
        self,
        source: Path,
        category: FileCategory,
        *,
        extension: str,
        move: bool = True,
    ) -> tuple[AllocatedPath, int]:
        """Bring a worker-produced file (e.g. from a temp workspace) into the
        tree and return its allocated location plus size in bytes."""
        if not source.is_file():
            raise StorageError(f"Cannot import missing file: {source.name}")
        allocated = self.allocate(category, extension)
        try:
            if move:
                shutil.move(str(source), allocated.absolute_path)
            else:
                shutil.copy2(source, allocated.absolute_path)
        except OSError as exc:  # disk full, permissions, ...
            raise StorageError("Failed to store the processed file.") from exc
        return allocated, allocated.absolute_path.stat().st_size

    def open_read(self, category: FileCategory, relative_path: str) -> BinaryIO:
        path = self.resolve(category, relative_path)
        return path.open("rb")

    def delete(self, category: FileCategory, relative_path: str) -> bool:
        """Remove a file from disk. Missing files are treated as deleted."""
        try:
            path = self.resolve(category, relative_path)
        except StorageError:
            return False
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            logger.warning("storage_delete_failed", path=relative_path)
            return False


# Storage has no per-request state; a module-level instance is safe to share.
_storage: LocalStorageService | None = None


def get_storage() -> LocalStorageService:
    global _storage
    if _storage is None:
        _storage = LocalStorageService()
    return _storage
