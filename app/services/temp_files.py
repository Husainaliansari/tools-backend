"""Temporary file management.

Workers do all their scratch work inside a *workspace* — a unique directory
under ``<STORAGE_ROOT>/temp/`` that is removed when the work finishes, no
matter how it finishes. The cleanup scheduler additionally purges workspaces
that outlive ``TEMP_FILE_MAX_AGE_MINUTES`` (crashed workers, kill -9, ...).
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


def create_workspace(prefix: str = "job") -> Path:
    """Create and return a fresh scratch directory under temp/."""
    settings = get_settings()
    workspace = settings.TEMP_DIR / f"{prefix}-{uuid.uuid4().hex}"
    workspace.mkdir(parents=True, exist_ok=False)
    return workspace


def remove_workspace(workspace: Path) -> None:
    """Delete a workspace tree, tolerating files locked by stragglers."""
    shutil.rmtree(workspace, ignore_errors=True)


@contextmanager
def temp_workspace(prefix: str = "job") -> Iterator[Path]:
    """Context-managed scratch directory: always removed on exit."""
    workspace = create_workspace(prefix)
    try:
        yield workspace
    finally:
        remove_workspace(workspace)


def purge_stale_workspaces(*, max_age_minutes: int | None = None) -> int:
    """Remove orphaned temp workspaces older than the configured age.

    Returns the number of directories removed. Used by the cleanup scheduler.
    """
    settings = get_settings()
    max_age = max_age_minutes or settings.TEMP_FILE_MAX_AGE_MINUTES
    cutoff = datetime.now(UTC) - timedelta(minutes=max_age)
    removed = 0

    if not settings.TEMP_DIR.is_dir():
        return 0

    for entry in settings.TEMP_DIR.iterdir():
        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime < cutoff:
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            removed += 1

    if removed:
        logger.info("temp_workspaces_purged", count=removed)
    return removed
