"""File-domain exceptions (upload, validation, storage, download)."""

from __future__ import annotations

from http import HTTPStatus

from app.constants import ErrorCode
from app.exceptions.base import AppException


class FileTooLargeError(AppException):
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    error_code = ErrorCode.FILE_TOO_LARGE
    message = "The uploaded file exceeds the maximum allowed size."


class TooManyFilesError(AppException):
    status_code = HTTPStatus.BAD_REQUEST
    error_code = ErrorCode.TOO_MANY_FILES
    message = "Too many files in a single upload."


class UnsupportedFileTypeError(AppException):
    status_code = HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    error_code = ErrorCode.UNSUPPORTED_FILE_TYPE
    message = "This file type is not supported."


class FileCorruptedError(AppException):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = ErrorCode.FILE_CORRUPTED
    message = "The file appears to be corrupted or is not what it claims to be."


class FileNotFoundAppError(AppException):
    status_code = HTTPStatus.NOT_FOUND
    error_code = ErrorCode.FILE_NOT_FOUND
    message = "The requested file was not found."


class FileExpiredError(AppException):
    status_code = HTTPStatus.GONE
    error_code = ErrorCode.FILE_EXPIRED
    message = "This file has expired and is no longer available."


class StorageError(AppException):
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code = ErrorCode.STORAGE_ERROR
    message = "A storage error occurred while handling the file."
