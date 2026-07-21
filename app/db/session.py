"""Database engine and session management.

Configures a single async SQLAlchemy 2.x engine and session factory for the
process, plus a FastAPI dependency (:func:`get_db`) that yields a request-scoped
session with correct transaction/rollback semantics.

Nothing here connects to the database at import time — the engine lazily opens
connections on first use.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

if settings.APP_ENV == "testing":
    # Pytest creates a fresh event loop per test; pooled asyncpg connections
    # cannot cross loops, so testing uses no pooling at all.
    engine: AsyncEngine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DB_ECHO,
        poolclass=NullPool,
        future=True,
    )
else:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DB_ECHO,
        pool_pre_ping=settings.DB_POOL_PRE_PING,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        future=True,
    )

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped async session.

    Rolls back automatically if the handler raises, and always closes the
    session. Commit is the caller's (repository/service) responsibility.
    """
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the engine's connection pool. Called on application shutdown."""
    await engine.dispose()
