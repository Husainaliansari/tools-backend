"""Unit tests for the local storage service and temp-file manager."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.constants import FileCategory
from app.exceptions.files import FileTooLargeError, StorageError
from app.services.storage import LocalStorageService
from app.services.temp_files import purge_stale_workspaces, temp_workspace


@pytest.fixture()
def storage() -> LocalStorageService:
    service = LocalStorageService()
    service.ensure_structure()
    return service


class FakeAsyncReader:
    """Minimal async reader mimicking Starlette's UploadFile."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._data)
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


class TestStructure:
    def test_ensure_structure_creates_all_directories(self, storage):
        settings = get_settings()
        for directory in (
            settings.UPLOADS_DIR,
            settings.PROCESSED_DIR,
            settings.TEMP_DIR,
            settings.THUMBNAILS_DIR,
            settings.LOGS_DIR,
        ):
            assert directory.is_dir()


class TestAllocateAndResolve:
    def test_allocate_creates_date_sharded_path(self, storage):
        allocated = storage.allocate(FileCategory.UPLOAD, "pdf")
        assert allocated.absolute_path.parent.is_dir()
        assert allocated.relative_path.endswith(".pdf")
        # YYYY/MM/DD/<uuid>.pdf
        assert len(allocated.relative_path.split("/")) == 4

    def test_resolve_round_trips(self, storage):
        allocated = storage.allocate(FileCategory.PROCESSED, "pdf")
        resolved = storage.resolve(FileCategory.PROCESSED, allocated.relative_path)
        assert resolved == allocated.absolute_path

    def test_resolve_rejects_traversal(self, storage):
        with pytest.raises(StorageError):
            storage.resolve(FileCategory.UPLOAD, "../../secrets.txt")


class TestWriteStream:
    @pytest.mark.asyncio
    async def test_writes_content_with_streaming_checksum(self, storage):
        import hashlib

        allocated = storage.allocate(FileCategory.UPLOAD, "pdf")
        data = b"%PDF-1.7 " + b"x" * 1000
        written, checksum = await storage.write_stream(
            FakeAsyncReader(data), allocated.absolute_path, max_bytes=10_000
        )
        assert written == len(data)
        assert checksum == hashlib.sha256(data).hexdigest()
        assert allocated.absolute_path.read_bytes() == data

    @pytest.mark.asyncio
    async def test_enforces_size_cap_and_removes_partial(self, storage):
        allocated = storage.allocate(FileCategory.UPLOAD, "pdf")
        with pytest.raises(FileTooLargeError):
            await storage.write_stream(
                FakeAsyncReader(b"x" * 5000), allocated.absolute_path, max_bytes=100
            )
        assert not allocated.absolute_path.exists()

    @pytest.mark.asyncio
    async def test_first_chunk_counts_toward_cap(self, storage):
        allocated = storage.allocate(FileCategory.UPLOAD, "pdf")
        with pytest.raises(FileTooLargeError):
            await storage.write_stream(
                FakeAsyncReader(b""),
                allocated.absolute_path,
                max_bytes=10,
                first_chunk=b"x" * 50,
            )


class TestImportFile:
    def test_moves_file_into_processed(self, storage, tmp_path):
        source = tmp_path / "out.pdf"
        source.write_bytes(b"%PDF-1.7 result")
        allocated, size = storage.import_file(
            source, FileCategory.PROCESSED, extension="pdf"
        )
        assert not source.exists()
        assert allocated.absolute_path.is_file()
        assert size == len(b"%PDF-1.7 result")

    def test_missing_source_raises(self, storage, tmp_path):
        with pytest.raises(StorageError):
            storage.import_file(
                tmp_path / "nope.pdf", FileCategory.PROCESSED, extension="pdf"
            )


class TestTempWorkspace:
    def test_workspace_created_and_removed(self, storage):
        settings = get_settings()
        with temp_workspace(prefix="test") as workspace:
            assert workspace.is_dir()
            assert workspace.parent == settings.TEMP_DIR
            (workspace / "scratch.bin").write_bytes(b"data")
        assert not workspace.exists()

    def test_workspace_removed_on_error(self, storage):
        try:
            with temp_workspace(prefix="test") as workspace:
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert not workspace.exists()

    def test_purge_stale_removes_old_workspaces(self, storage):
        import os
        import time

        with temp_workspace(prefix="live") as _live:
            settings = get_settings()
            stale = settings.TEMP_DIR / "stale-workspace"
            stale.mkdir()
            old = time.time() - 3600 * 24
            os.utime(stale, (old, old))

            removed = purge_stale_workspaces(max_age_minutes=60)
            assert removed == 1
            assert not stale.exists()
            assert _live.exists()
