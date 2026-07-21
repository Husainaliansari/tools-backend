"""Job-domain exceptions (background processing lifecycle)."""

from __future__ import annotations

from http import HTTPStatus

from app.constants import ErrorCode
from app.exceptions.base import AppException


class JobNotFoundError(AppException):
    status_code = HTTPStatus.NOT_FOUND
    error_code = ErrorCode.JOB_NOT_FOUND
    message = "The requested job was not found."


class JobNotCompletedError(AppException):
    status_code = HTTPStatus.CONFLICT
    error_code = ErrorCode.JOB_NOT_COMPLETED
    message = "The job has not completed yet; its results are not available."


class JobAlreadyFinishedError(AppException):
    status_code = HTTPStatus.CONFLICT
    error_code = ErrorCode.JOB_ALREADY_FINISHED
    message = "The job has already finished and cannot be modified."


class ProcessingError(Exception):
    """Raised inside workers when a tool fails on a given input.

    Deliberately *not* an :class:`AppException` — it never crosses the HTTP
    boundary directly. The task base catches it and records ``error_code`` /
    ``error_message`` on the job row, which the status API then surfaces.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str = ErrorCode.PROCESSING_FAILED,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
