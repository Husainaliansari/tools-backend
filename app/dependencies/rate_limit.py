"""Upload rate limiting (Redis fixed-window counter, fail-open).

Fail-open by design: a Redis outage degrades to "no rate limiting", never to
"no uploads". Limits are per client IP per minute.
"""

from __future__ import annotations

import time
from http import HTTPStatus

from fastapi import Request

from app.config import get_settings
from app.constants import ErrorCode
from app.db.redis import get_redis
from app.exceptions.base import AppException
from app.logging import get_logger

logger = get_logger(__name__)


class RateLimitedError(AppException):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    error_code = ErrorCode.RATE_LIMITED
    message = "Too many uploads. Please wait a minute and try again."


async def upload_rate_limit(request: Request) -> None:
    """FastAPI dependency enforcing the per-IP upload rate limit."""
    settings = get_settings()
    limit = settings.UPLOAD_RATE_LIMIT_PER_MINUTE
    if limit <= 0:  # disabled
        return

    client_ip = request.client.host if request.client else "unknown"
    window = int(time.time() // 60)
    key = f"ratelimit:upload:{client_ip}:{window}"

    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            # Window key lives slightly longer than the window itself.
            await redis.expire(key, 90)
    except Exception:
        logger.warning("rate_limit_backend_unavailable", client=client_ip)
        return  # fail-open

    if count > limit:
        logger.info("upload_rate_limited", client=client_ip, count=count)
        raise RateLimitedError()
