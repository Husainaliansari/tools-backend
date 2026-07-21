"""Application exception hierarchy.

All expected, domain-level failures should raise a subclass of
:class:`AppException`. The centralised handlers (see ``handlers.py``) translate
these into the standard :class:`app.schemas.response.ErrorResponse` envelope
with the correct HTTP status code.

Only the framework-level base classes live here; feature-specific exceptions
inherit from these as the application grows.
"""

from __future__ import annotations

from http import HTTPStatus

from app.constants import ErrorCode
from app.schemas.response import ErrorDetail


class AppException(Exception):
    """Base class for all handled application exceptions."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code: str = ErrorCode.INTERNAL_SERVER_ERROR
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        self.message = message or self.message
        self.error_code = error_code or self.error_code
        self.status_code = status_code or self.status_code
        self.details = details or []
        super().__init__(self.message)


class BadRequestError(AppException):
    status_code = HTTPStatus.BAD_REQUEST
    error_code = ErrorCode.BAD_REQUEST
    message = "The request could not be processed."


class ValidationError(AppException):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = ErrorCode.VALIDATION_ERROR
    message = "The request payload failed validation."


class UnauthorizedError(AppException):
    status_code = HTTPStatus.UNAUTHORIZED
    error_code = ErrorCode.UNAUTHORIZED
    message = "Authentication is required."


class ForbiddenError(AppException):
    status_code = HTTPStatus.FORBIDDEN
    error_code = ErrorCode.FORBIDDEN
    message = "You do not have permission to perform this action."


class NotFoundError(AppException):
    status_code = HTTPStatus.NOT_FOUND
    error_code = ErrorCode.NOT_FOUND
    message = "The requested resource was not found."


class ConflictError(AppException):
    status_code = HTTPStatus.CONFLICT
    error_code = ErrorCode.CONFLICT
    message = "The request conflicts with the current state of the resource."


class ServiceUnavailableError(AppException):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    error_code = ErrorCode.SERVICE_UNAVAILABLE
    message = "The service is temporarily unavailable."
