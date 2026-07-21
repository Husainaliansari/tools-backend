"""Centralised exception handlers.

Registers a small set of handlers on the FastAPI application so that *every*
error — whether a deliberate :class:`AppException`, a framework
``HTTPException``, a request-validation failure, or a wholly unexpected
exception — is serialised into the standard :class:`ErrorResponse` envelope.

This keeps error handling in one place (Separation of Concerns) and guarantees
clients never see a raw stack trace or inconsistent error shape.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.constants import ErrorCode
from app.core.context import get_request_id
from app.exceptions.base import AppException
from app.logging import get_logger
from app.schemas.response import ErrorDetail, ErrorInfo, ErrorResponse

logger = get_logger(__name__)


def _render(status_code: int, error: ErrorInfo) -> JSONResponse:
    """Serialise an :class:`ErrorInfo` into the standard error envelope."""
    payload = ErrorResponse(error=error, request_id=get_request_id())
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def app_exception_handler(_request: Request, exc: AppException) -> JSONResponse:
    """Handle deliberate, domain-level exceptions."""
    logger.warning(
        "application_exception",
        error_code=exc.error_code,
        status_code=exc.status_code,
        message=exc.message,
    )
    return _render(
        exc.status_code,
        ErrorInfo(code=exc.error_code, message=exc.message, details=exc.details),
    )


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle request payload/query/path validation errors."""
    details = [
        ErrorDetail(
            message=err.get("msg", "Invalid value."),
            field=".".join(str(loc) for loc in err.get("loc", []) if loc != "body"),
            type=err.get("type"),
        )
        for err in exc.errors()
    ]
    logger.info("request_validation_error", error_count=len(details))
    return _render(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        ErrorInfo(
            code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed.",
            details=details,
        ),
    )


async def http_exception_handler(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle framework ``HTTPException`` (e.g. 404 from routing)."""
    return _render(
        exc.status_code,
        ErrorInfo(code=f"HTTP_{exc.status_code}", message=str(exc.detail)),
    )


async def unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all for unexpected errors. Never leak internals to clients."""
    logger.exception("unhandled_exception", exc_info=exc)
    return _render(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorInfo(
            code=ErrorCode.INTERNAL_SERVER_ERROR,
            message="An unexpected error occurred.",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the application.

    Starlette's ``add_exception_handler`` stub types the handler's second
    argument as the base ``Exception``; our handlers narrow to specific
    subclasses, so the targeted ignores below are expected and safe.
    """
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
