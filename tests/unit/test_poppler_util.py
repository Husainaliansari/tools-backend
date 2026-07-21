"""Unit tests for the Poppler rasterisation utility (mocked command layer)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions.jobs import ProcessingError
from app.utils import command as command_mod
from app.utils import poppler
from app.utils.command import CommandError, CommandResult


def _fake_result(command: list[str]) -> CommandResult:
    return CommandResult(
        command=command, returncode=0, stdout="", stderr="", duration_seconds=0.1
    )


def _write_pages(command: list[str], pages: list[int], extension: str) -> None:
    prefix = Path(command[-1])
    for page in pages:
        (prefix.parent / f"{prefix.name}-{page}.{extension}").write_bytes(b"img")


class TestPdfToImages:
    def test_jpeg_command_shape_and_ordering(self, tmp_path, monkeypatch):
        captured: dict[str, list[str]] = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            # Write out of order to prove sorting is numeric, not lexical.
            _write_pages(command, [10, 2, 1], "jpg")
            return _fake_result(command)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")

        pages = poppler.pdf_to_images(
            source, tmp_path, image_format="jpeg", dpi=200, quality=80
        )

        command = captured["command"]
        assert "-jpeg" in command
        assert command[command.index("-r") + 1] == "200"
        assert command[command.index("-jpegopt") + 1] == "quality=80"
        assert [n for n, _ in pages] == [1, 2, 10]

    def test_png_omits_jpeg_options(self, tmp_path, monkeypatch):
        captured: dict[str, list[str]] = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            _write_pages(command, [1], "png")
            return _fake_result(command)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")

        poppler.pdf_to_images(source, tmp_path, image_format="png")
        assert "-png" in captured["command"]
        assert "-jpegopt" not in captured["command"]

    def test_page_range_flags(self, tmp_path, monkeypatch):
        captured: dict[str, list[str]] = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            _write_pages(command, [2, 3], "jpg")
            return _fake_result(command)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")

        pages = poppler.pdf_to_images(source, tmp_path, first_page=2, last_page=3)
        command = captured["command"]
        assert command[command.index("-f") + 1] == "2"
        assert command[command.index("-l") + 1] == "3"
        assert [n for n, _ in pages] == [2, 3]

    def test_no_output_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(command_mod, "run_command", lambda c, **k: _fake_result(c))
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")

        with pytest.raises(ProcessingError, match="produced no pages"):
            poppler.pdf_to_images(source, tmp_path)

    def test_missing_binary_becomes_processing_error(self, tmp_path, monkeypatch):
        def fake_run(command, **_kwargs):
            raise CommandError("not found", command=command)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")

        with pytest.raises(ProcessingError, match="not available"):
            poppler.pdf_to_images(source, tmp_path)
