"""Dependencies package.

Home for reusable FastAPI dependencies (dependency-injection providers) that are
shared across endpoints: database/redis session providers, pagination, and
(later) authenticated-user resolution. Centralising them keeps endpoints thin
and testable.
"""

from app.db import get_db, get_redis
from app.dependencies.pagination import PaginationParams, pagination_params

__all__ = ["PaginationParams", "get_db", "get_redis", "pagination_params"]
