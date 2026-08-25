"""Schema package.

Houses shared/base Pydantic schemas, the standard response envelopes, and the
file/job read models shared by every tool endpoint. Feature-specific
request/response models are added in their own modules and inherit from
:class:`app.schemas.base.BaseSchema`.
"""

from app.schemas.analytics import PageVisitCreate
from app.schemas.base import BaseSchema, ORMSchema
from app.schemas.feedback import CaptchaChallenge, FeedbackOut
from app.schemas.file import FileInfo, UploadResult
from app.schemas.job import JobCreateRequest, JobError, JobInfo
from app.schemas.response import (
    ErrorDetail,
    ErrorInfo,
    ErrorResponse,
    SuccessResponse,
)

__all__ = [
    "BaseSchema",
    "CaptchaChallenge",
    "ErrorDetail",
    "ErrorInfo",
    "ErrorResponse",
    "FeedbackOut",
    "FileInfo",
    "JobCreateRequest",
    "JobError",
    "JobInfo",
    "ORMSchema",
    "PageVisitCreate",
    "SuccessResponse",
    "UploadResult",
]
