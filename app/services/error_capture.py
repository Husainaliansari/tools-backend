"""Best-effort capture of unhandled errors into the admin Error Logs table.

Called from the catch-all exception handler. Deduplicates by a fingerprint
(exception type + first application stack frame) and increments the occurrence
count instead of inserting duplicates. Any failure here is swallowed — error
capture must never turn a 500 into a crash.
"""

from __future__ import annotations

import hashlib
import traceback
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db.session import SessionFactory
from app.logging import get_logger
from app.models.admin import ErrorLog

logger = get_logger(__name__)


def _fingerprint(exc: Exception) -> str:
    tb = exc.__traceback__
    frame = ""
    if tb is not None:
        last = traceback.extract_tb(tb)[-1:]
        if last:
            frame = f"{last[0].filename}:{last[0].name}"
    raw = f"{type(exc).__name__}:{frame}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


async def capture_exception(exc: Exception, *, path: str | None = None) -> None:
    try:
        fp = _fingerprint(exc)
        message = f"{type(exc).__name__}: {exc}"[:500]
        stack = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )[:8000]
        now = datetime.now(UTC)
        async with SessionFactory() as session:
            existing = (
                await session.execute(
                    select(ErrorLog.id).where(ErrorLog.fingerprint == fp)
                )
            ).scalar_one_or_none()
            if existing is not None:
                await session.execute(
                    update(ErrorLog)
                    .where(ErrorLog.id == existing)
                    .values(
                        count=ErrorLog.count + 1,
                        last_seen_at=now,
                        resolved=False,
                        message=message,
                    )
                )
            else:
                session.add(
                    ErrorLog(
                        level="error",
                        message=message,
                        service="api",
                        path=path,
                        stack=stack,
                        fingerprint=fp,
                        count=1,
                        last_seen_at=now,
                    )
                )
            await session.commit()
    except Exception as capture_exc:  # pragma: no cover - never propagate
        logger.debug("error_capture_failed", error=str(capture_exc))
