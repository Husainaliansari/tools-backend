"""Database package.

Exposes the declarative base, engine/session primitives, and Redis accessors::

    from app.db import Base, get_db, get_redis
"""

from app.db.base import Base
from app.db.redis import close_redis, connection_pool, get_redis
from app.db.session import SessionFactory, dispose_engine, engine, get_db

__all__ = [
    "Base",
    "SessionFactory",
    "close_redis",
    "connection_pool",
    "dispose_engine",
    "engine",
    "get_db",
    "get_redis",
]
