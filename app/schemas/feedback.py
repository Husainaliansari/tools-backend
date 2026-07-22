"""Feedback API schemas.

The submission itself arrives as ``multipart/form-data`` (it can carry a file),
so the endpoint parses individual ``Form``/``File`` fields rather than a JSON
body model. These schemas cover the *responses*: the captcha challenge issued
to the client and the read model returned after a successful submission.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.constants import FeedbackCategory
from app.schemas.base import BaseSchema, ORMSchema


class CaptchaChallenge(BaseSchema):
    """A lightweight math challenge the client must solve before submitting."""

    token: str = Field(..., description="Signed, time-limited challenge token.")
    question: str = Field(..., description="Human-readable prompt, e.g. '3 + 4 ='.")
    expires_in: int = Field(..., description="Seconds until the token expires.")


class FeedbackOut(ORMSchema):
    """Read model returned to the client after a submission is stored."""

    id: uuid.UUID
    name: str
    email: str
    subject: str | None = None
    category: FeedbackCategory
    message: str
    attachment_name: str | None = None
    created_at: datetime
