"""Synchronous database engine and session for Celery workers.

Celery tasks run in synchronous worker processes, so they cannot share the
async engine used by the API. This module provides a lazily-created sync
engine (psycopg driver) and a context-managed session with commit/rollback
semantics suited to task code.

The engine is created on first use — importing this module in the API process
costs nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_sync_engine() -> Engine:
    """Return the process-wide synchronous engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.SYNC_DATABASE_URL,
            echo=settings.DB_ECHO,
            pool_pre_ping=settings.DB_POOL_PRE_PING,
            # Workers hold few concurrent sessions; keep the pool small.
            pool_size=5,
            max_overflow=5,
            pool_recycle=settings.DB_POOL_RECYCLE,
            future=True,
        )
    return _engine


def _get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_sync_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@contextmanager
def sync_session() -> Iterator[Session]:
    """Yield a session that commits on success and rolls back on error."""
    session = _get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
