"""Security headers middleware.

Adds a conservative set of security-related response headers to every response.
Values are set with ``setdefault`` semantics so individual endpoints may
override them when necessary.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply baseline security headers to all responses."""

    def __init__(self, app: ASGIApp, *, enable_hsts: bool = False) -> None:
        super().__init__(app)
        self._enable_hsts = enable_hsts

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        headers = response.headers

        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        headers.setdefault("X-XSS-Protection", "0")

        # HSTS should only be sent over HTTPS in production deployments.
        if self._enable_hsts:
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
