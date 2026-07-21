"""Request-scoped context helpers.

Provides a small, dependency-free API for correlating log lines and responses
with a single request. Values are stored in ``structlog.contextvars`` so every
log statement emitted while handling a request automatically carries the
``request_id`` and ``correlation_id`` without threading them through call sites.
"""

from __future__ import annotations

import structlog

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"

_REQUEST_ID_KEY = "request_id"
_CORRELATION_ID_KEY = "correlation_id"


def bind_request_context(*, request_id: str, correlation_id: str) -> None:
    """Bind identifiers to the current request's logging context."""
    structlog.contextvars.bind_contextvars(
        **{_REQUEST_ID_KEY: request_id, _CORRELATION_ID_KEY: correlation_id}
    )


def clear_request_context() -> None:
    """Clear all context variables bound for the current request."""
    structlog.contextvars.clear_contextvars()


def get_request_id() -> str | None:
    """Return the request id bound to the current context, if any."""
    return structlog.contextvars.get_contextvars().get(_REQUEST_ID_KEY)


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current context, if any."""
    return structlog.contextvars.get_contextvars().get(_CORRELATION_ID_KEY)
