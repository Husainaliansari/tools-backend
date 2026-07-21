"""Unit tests for parallel chunked PDF rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.utils import command as command_mod
from app.utils import poppler
from app.utils.command import CommandResult


def _fake_run_factory(calls: list[list[str]]):
    def fake_run(command, **_kwargs):
        calls.append(command)
        prefix = Path(command[-1])
        first = int(command[command.index("-f") + 1]) if "-f" in command else 1
        last = int(command[command.index("-l") + 1]) if "-l" in command else 3
        prefix.parent.mkdir(parents=True, exist_ok=True)
        for page in range(first, last + 1):
            (prefix.parent / f"{prefix.name}-{page}.jpg").write_bytes(b"img")
        return CommandResult(
            command=command, returncode=0, stdout="", stderr="", duration_seconds=0.0
        )

    return fake_run


class TestPdfToImagesAuto:
    def test_small_documents_render_in_one_call(self, tmp_path, monkeypatch):
        calls: list[list[str]] = []
        monkeypatch.setattr(command_mod, "run_command", _fake_run_factory(calls))
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")

        pages = poppler.pdf_to_images_auto(source, tmp_path, total_pages=5)

        assert len(calls) == 1
        assert [n for n, _ in pages] == [1, 2, 3, 4, 5]

    def test_large_documents_fan_out_into_chunks(self, tmp_path, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "RENDER_PARALLEL_THRESHOLD_PAGES", 4)
        monkeypatch.setattr(settings, "RENDER_PARALLEL_WORKERS", 3)
        calls: list[list[str]] = []
        monkeypatch.setattr(command_mod, "run_command", _fake_run_factory(calls))
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")

        pages = poppler.pdf_to_images_auto(source, tmp_path, total_pages=10)

        assert len(calls) == 3  # ceil(10/3)=4 pages per chunk → 3 chunks
        # Every source page rendered exactly once, in order.
        assert [n for n, _ in pages] == list(range(1, 11))
        # Chunks rendered into isolated subdirectories.
        chunk_dirs = {Path(c[-1]).parent.name for c in calls}
        assert chunk_dirs == {"chunk-0", "chunk-1", "chunk-2"}

    @pytest.mark.parametrize("first,last,expected", [(3, 9, 7), (None, 6, 6)])
    def test_page_range_respected(self, tmp_path, monkeypatch, first, last, expected):
        settings = get_settings()
        monkeypatch.setattr(settings, "RENDER_PARALLEL_THRESHOLD_PAGES", 3)
        monkeypatch.setattr(settings, "RENDER_PARALLEL_WORKERS", 2)
        calls: list[list[str]] = []
        monkeypatch.setattr(command_mod, "run_command", _fake_run_factory(calls))
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")

        pages = poppler.pdf_to_images_auto(
            source, tmp_path, total_pages=12, first_page=first, last_page=last
        )
        assert len(pages) == expected
        assert pages[0][0] == (first or 1)
