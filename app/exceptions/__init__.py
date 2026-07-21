"""Exceptions package.

Exposes the application exception hierarchy and the handler-registration
helper::

    from app.exceptions import NotFoundError, register_exception_handlers
"""

from app.exceptions.base import (
    AppException,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from app.exceptions.files import (
    FileCorruptedError,
    FileExpiredError,
    FileNotFoundAppError,
    FileTooLargeError,
    StorageError,
    TooManyFilesError,
    UnsupportedFileTypeError,
)
from app.exceptions.handlers import register_exception_handlers
from app.exceptions.jobs import (
    JobAlreadyFinishedError,
    JobNotCompletedError,
    JobNotFoundError,
    ProcessingError,
)

__all__ = [
    "AppException",
    "BadRequestError",
    "ConflictError",
    "FileCorruptedError",
    "FileExpiredError",
    "FileNotFoundAppError",
    "FileTooLargeError",
    "ForbiddenError",
    "JobAlreadyFinishedError",
    "JobNotCompletedError",
    "JobNotFoundError",
    "NotFoundError",
    "ProcessingError",
    "ServiceUnavailableError",
    "StorageError",
    "TooManyFilesError",
    "UnauthorizedError",
    "UnsupportedFileTypeError",
    "ValidationError",
    "register_exception_handlers",
]
