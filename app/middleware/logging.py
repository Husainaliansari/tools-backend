"""Request logging middleware.

Emits a structured log line when a request starts and finishes (including
latency and response status). Because it runs inside the request-context
middleware, every line automatically carries the request/correlation ids.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.logging import get_logger

logger = get_logger("app.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured access logging with request latency."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        client_host = request.client.host if request.client else None

        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            client=client_host,
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
