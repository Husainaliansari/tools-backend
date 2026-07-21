"""Unit tests for the concurrent per-file task helper."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from app.exceptions.jobs import ProcessingError
from app.tasks.base import (
    ProducedFile,
    ToolRunContext,
    process_each_input_parallel,
)


def _context(tmp_path: Path, names: list[str], report=None) -> ToolRunContext:
    return ToolRunContext(
        job=None,  # not touched by the helper
        input_paths=[tmp_path / name for name in names],
        input_names=names,
        options={},
        workspace=tmp_path,
        report_progress=report or (lambda _p: None),
    )


class TestProcessEachInputParallel:
    def test_output_order_matches_input_order(self, tmp_path):
        """Files finishing out of order must not reorder the outputs."""
        names = ["a.pptx", "b.pptx", "c.pptx"]
        delays = {"a.pptx": 0.15, "b.pptx": 0.05, "c.pptx": 0.0}

        def operate(path, name, index):
            time.sleep(delays[name])
            return ProducedFile(tmp_path / f"{name}.pdf", f"{name}.pdf")

        produced = process_each_input_parallel(
            _context(tmp_path, names), operate, max_workers=3
        )
        assert [item.download_name for item in produced] == [
            "a.pptx.pdf",
            "b.pptx.pdf",
            "c.pptx.pdf",
        ]

    def test_progress_reported_from_calling_thread_only(self, tmp_path):
        """The DB-bound progress callback must stay on the task's thread."""
        names = ["a.pptx", "b.pptx", "c.pptx"]
        caller = threading.get_ident()
        reports: list[tuple[int, int]] = []

        def report(progress: int) -> None:
            reports.append((progress, threading.get_ident()))

        def operate(path, name, index):
            return ProducedFile(tmp_path / f"{name}.pdf", f"{name}.pdf")

        process_each_input_parallel(
            _context(tmp_path, names, report), operate, max_workers=3
        )
        assert [progress for progress, _ in reports] == [30, 60, 90]
        assert all(thread == caller for _, thread in reports)

    def test_first_failure_fails_the_job(self, tmp_path):
        def operate(path, name, index):
            if name == "b.pptx":
                raise ProcessingError("bad file")
            return ProducedFile(tmp_path / f"{name}.pdf", f"{name}.pdf")

        with pytest.raises(ProcessingError, match="bad file"):
            process_each_input_parallel(
                _context(tmp_path, ["a.pptx", "b.pptx"]), operate, max_workers=2
            )

    def test_single_file_stays_sequential(self, tmp_path):
        """One input takes the plain path — no pointless thread pool."""
        threads: set[int] = set()

        def operate(path, name, index):
            threads.add(threading.get_ident())
            return ProducedFile(tmp_path / f"{name}.pdf", f"{name}.pdf")

        process_each_input_parallel(
            _context(tmp_path, ["a.pptx"]), operate, max_workers=8
        )
        assert threads == {threading.get_ident()}
