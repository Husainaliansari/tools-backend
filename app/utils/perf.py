"""Lightweight per-job phase timing for tool conversions.

A :class:`PerfTimer` accumulates named phase durations so a single structured
``job_perf`` log line can report where a conversion spent its wall-clock time —
loading inputs, preprocessing, the conversion itself, and exporting outputs.

Design notes:

* **Thread-safe.** Multi-file conversions run per-file work on a thread pool
  (see :func:`app.tasks.base.process_each_input_parallel`), so worker threads
  may record the same sub-phase concurrently. Accumulation is guarded by a
  lock.
* **Additive per name.** ``phases_ms[name]`` is the *sum of work time* spent in
  that phase across all calls, and ``counts[name]`` how many times it ran. For
  a sub-phase run on N threads this is aggregate work, not wall time — the
  top-level phases in :func:`run_tool_job` (which run sequentially on one
  thread) give the true wall-clock breakdown. Both are reported so the log is
  unambiguous.
* **Zero-overhead default.** Tools that don't care get :data:`NULL_TIMER`, a
  shared no-op instance, so ``ctx.perf.phase(...)`` is always safe to call.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager


class PerfTimer:
    """Accumulate named phase durations for one tool job."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._phases: dict[str, float] = {}
        self._counts: dict[str, int] = {}
        self._start = time.monotonic()

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Time a block and add its duration to phase ``name``."""
        started = time.monotonic()
        try:
            yield
        finally:
            self.add(name, time.monotonic() - started)

    def add(self, name: str, seconds: float) -> None:
        """Record ``seconds`` of work under phase ``name`` (thread-safe)."""
        with self._lock:
            self._phases[name] = self._phases.get(name, 0.0) + seconds
            self._counts[name] = self._counts.get(name, 0) + 1

    def summary(self) -> dict[str, object]:
        """Structured snapshot for logging: total wall time + per-phase work."""
        with self._lock:
            return {
                "total_ms": round((time.monotonic() - self._start) * 1000, 1),
                "phases_ms": {
                    name: round(seconds * 1000, 1)
                    for name, seconds in self._phases.items()
                },
                "phase_counts": dict(self._counts),
            }


class _NullTimer(PerfTimer):
    """No-op timer: ``phase``/``add`` do nothing, ``summary`` is empty."""

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:  # noqa: ARG002
        yield

    def add(self, name: str, seconds: float) -> None:  # noqa: ARG002
        return

    def summary(self) -> dict[str, object]:
        return {}


#: Shared no-op timer for contexts that don't record timings.
NULL_TIMER: PerfTimer = _NullTimer()
