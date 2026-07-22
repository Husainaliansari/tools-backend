"""Application-wide constants and enumerations.

Central home for values that are shared across layers and must stay in sync
(error codes, header names, common enums). Keeping them here avoids "magic
strings" scattered through the codebase (DRY).
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable, machine-readable error codes surfaced to API clients."""

    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

    # Files
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TOO_MANY_FILES = "TOO_MANY_FILES"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_CORRUPTED = "FILE_CORRUPTED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_EXPIRED = "FILE_EXPIRED"
    STORAGE_ERROR = "STORAGE_ERROR"

    # Jobs
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_NOT_COMPLETED = "JOB_NOT_COMPLETED"
    JOB_ALREADY_FINISHED = "JOB_ALREADY_FINISHED"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    PROCESSING_TIMEOUT = "PROCESSING_TIMEOUT"

    # Feedback
    FEEDBACK_DAILY_LIMIT = "FEEDBACK_DAILY_LIMIT"
    CAPTCHA_INVALID = "CAPTCHA_INVALID"


class FeedbackCategory(StrEnum):
    """Kind of feedback a visitor is submitting (mirrors the frontend dropdown)."""

    GENERAL = "general"
    BUG = "bug"
    FEATURE = "feature"
    UI_UX = "ui_ux"
    PERFORMANCE = "performance"
    OTHER = "other"


class FileStatus(StrEnum):
    """Lifecycle of a stored file (upload or processed output)."""

    ACTIVE = "active"
    EXPIRED = "expired"
    DELETED = "deleted"


class FileCategory(StrEnum):
    """Which branch of the storage tree a file lives in."""

    UPLOAD = "upload"
    PROCESSED = "processed"
    THUMBNAIL = "thumbnail"


class JobStatus(StrEnum):
    """Lifecycle of a background processing job."""

    PENDING = "pending"  # created, not yet handed to the broker
    QUEUED = "queued"  # enqueued on Celery, waiting for a worker
    PROCESSING = "processing"  # a worker is executing the tool
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"  # outputs purged by the cleanup scheduler

    @property
    def is_terminal(self) -> bool:
        return self in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.EXPIRED,
        }


class JobFileRole(StrEnum):
    """Whether a file is a job's input or output."""

    INPUT = "input"
    OUTPUT = "output"


class ToolSlug(StrEnum):
    """Canonical identifiers for the PDF tools (mirrors the frontend slugs)."""

    COMPRESS = "compress"
    MERGE = "merge"
    SPLIT = "split"
    ROTATE = "rotate"
    DELETE_PAGES = "delete-pages"
    EXTRACT_PAGES = "extract-pages"
    REORDER_PAGES = "reorder"
    PDF_TO_WORD = "pdf-to-word"
    WORD_TO_PDF = "word-to-pdf"
    EXCEL_TO_PDF = "excel-to-pdf"
    PPT_TO_PDF = "ppt-to-pdf"
    PDF_TO_JPG = "pdf-to-jpg"
    PDF_TO_PNG = "pdf-to-png"
    JPG_TO_PDF = "jpg-to-pdf"
    PNG_TO_PDF = "png-to-pdf"
    WATERMARK = "watermark"
    REMOVE_WATERMARK = "remove-watermark"
    HEADER_FOOTER = "header-footer"
    PAGE_NUMBERS = "page-numbers"
    PROTECT = "protect"
    UNLOCK = "unlock"
    OCR = "ocr"
    REPAIR = "repair"
    COMPRESS_SCANNED = "compress-scanned"
    METADATA = "metadata"
    COMPARE = "compare"
    REDACT = "redact"
    FILL_FORMS = "fill-forms"
    SIGN = "sign"


__all__ = [
    "ErrorCode",
    "FeedbackCategory",
    "FileCategory",
    "FileStatus",
    "JobFileRole",
    "JobStatus",
    "ToolSlug",
]
