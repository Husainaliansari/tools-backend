"""Request context middleware.

Assigns (or honours an inbound) request id and correlation id for every
request, binds them to the structlog context so all logs are correlated, exposes
them on ``request.state``, and echoes them back on the response headers.

This middleware should be the outermost in the stack so that identifiers are
available to every other middleware and handler.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    bind_request_context,
    clear_request_context,
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request/correlation ids to the logging context and headers."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or request_id

        bind_request_context(request_id=request_id, correlation_id=correlation_id)
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            return response
        finally:
            clear_request_context()
