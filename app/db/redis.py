"""Redis connection configuration.

Provides a shared async Redis connection pool and a client accessor. This is
*configuration only* — no caching, rate-limiting, or session logic is
implemented here (that arrives with features that need it).
"""

from __future__ import annotations

from redis.asyncio import ConnectionPool, Redis

from app.config import get_settings

settings = get_settings()

# A single pool is shared across the process; clients are cheap handles onto it.
connection_pool: ConnectionPool = ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=50,
)


def get_redis() -> Redis:
    """Return a Redis client backed by the shared connection pool."""
    return Redis(connection_pool=connection_pool)


async def close_redis() -> None:
    """Disconnect the shared pool. Called on application shutdown."""
    await connection_pool.disconnect()
