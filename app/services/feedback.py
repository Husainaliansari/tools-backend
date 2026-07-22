"""Feedback submission service.

Orchestrates a single submission of the public *Feedback & Suggestions* form:
captcha verification, the once-per-day anti-spam limit, attachment validation,
persistence, and a best-effort notification email to the administrators.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import FeedbackCategory
from app.exceptions.base import ValidationError
from app.exceptions.feedback import CaptchaInvalidError, FeedbackDailyLimitError
from app.exceptions.files import FileTooLargeError, UnsupportedFileTypeError
from app.logging import get_logger
from app.models.feedback import Feedback
from app.repositories.feedback import FeedbackRepository
from app.services import captcha
from app.services.email import send_email

logger = get_logger(__name__)

# Leading magic bytes for the image types we accept. Guards against a spoofed
# Content-Type (a .exe renamed to .png) — the bytes must actually be an image.
_IMAGE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),  # RIFF....WEBP (checked below)
}

_CATEGORY_LABELS: dict[FeedbackCategory, str] = {
    FeedbackCategory.GENERAL: "General Feedback",
    FeedbackCategory.BUG: "Bug Report",
    FeedbackCategory.FEATURE: "Feature Request",
    FeedbackCategory.UI_UX: "UI/UX Suggestion",
    FeedbackCategory.PERFORMANCE: "Performance Issue",
    FeedbackCategory.OTHER: "Other",
}


@dataclass(frozen=True)
class Attachment:
    """A validated screenshot attachment."""

    filename: str
    content_type: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


def validate_attachment(
    *, filename: str | None, content_type: str | None, data: bytes
) -> Attachment:
    """Validate an uploaded screenshot (type, size, real image bytes)."""
    settings = get_settings()
    ctype = (content_type or "").split(";")[0].strip().lower()

    if ctype not in settings.FEEDBACK_ATTACHMENT_ALLOWED_TYPES:
        raise UnsupportedFileTypeError(
            "Attachments must be an image (JPG, JPEG, PNG or WebP)."
        )
    if len(data) == 0:
        raise ValidationError("The attachment is empty.")
    if len(data) > settings.FEEDBACK_ATTACHMENT_MAX_BYTES:
        raise FileTooLargeError("The attachment must be 1 MB or smaller.")

    signatures = _IMAGE_SIGNATURES.get(ctype, ())
    if not any(data.startswith(sig) for sig in signatures) or (
        ctype == "image/webp" and data[8:12] != b"WEBP"
    ):
        raise UnsupportedFileTypeError(
            "The attachment does not appear to be a valid image."
        )

    return Attachment(
        filename=(filename or "screenshot")[:255],
        content_type=ctype,
        data=data,
    )


class FeedbackService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FeedbackRepository(session)

    async def submit(
        self,
        *,
        name: str,
        email: str,
        message: str,
        category: str,
        subject: str | None,
        captcha_token: str,
        captcha_answer: str,
        honeypot: str | None,
        attachment: Attachment | None,
        client_ip: str | None,
        user_id: uuid.UUID | None,
    ) -> Feedback:
        # Honeypot: a hidden field only bots fill in. Pretend success (so we
        # don't teach scrapers the trick) but persist nothing.
        if honeypot:
            logger.info("feedback_honeypot_triggered", client=client_ip)
            return self._decoy(name=name, email=email, category=category, subject=subject, message=message)

        if not captcha.verify(captcha_token, captcha_answer):
            raise CaptchaInvalidError()

        try:
            parsed_category = FeedbackCategory(category)
        except ValueError as exc:
            raise ValidationError("Unknown feedback category.") from exc

        await self._enforce_daily_limit(email=email, client_ip=client_ip)

        feedback = Feedback(
            name=name.strip(),
            email=email.strip().lower(),
            subject=(subject or None),
            category=parsed_category,
            message=message.strip(),
            client_ip=client_ip,
            user_id=user_id,
        )
        if attachment is not None:
            feedback.attachment_name = attachment.filename
            feedback.attachment_content_type = attachment.content_type
            feedback.attachment_size = attachment.size
            feedback.attachment_data = attachment.data

        self.repo.add(feedback)
        await self.session.commit()
        await self.session.refresh(feedback)
        logger.info(
            "feedback_submitted",
            feedback_id=str(feedback.id),
            category=parsed_category.value,
            has_attachment=attachment is not None,
        )

        await self._notify_admins(feedback)
        return feedback

    async def _enforce_daily_limit(
        self, *, email: str, client_ip: str | None
    ) -> None:
        settings = get_settings()
        if settings.FEEDBACK_MAX_PER_DAY <= 0:
            return
        since = datetime.now(UTC) - timedelta(days=1)
        recent = await self.repo.count_recent(
            since=since, email=email, client_ip=client_ip
        )
        if recent >= settings.FEEDBACK_MAX_PER_DAY:
            raise FeedbackDailyLimitError()

    async def _notify_admins(self, feedback: Feedback) -> None:
        settings = get_settings()
        recipients = settings.FEEDBACK_ADMIN_EMAILS
        if not recipients:
            return
        label = _CATEGORY_LABELS.get(feedback.category, str(feedback.category))
        subject = f"[Feedback · {label}] {feedback.subject or 'New submission'}"
        body = (
            f"New feedback submitted via PDFly.\n\n"
            f"Category: {label}\n"
            f"Name:     {feedback.name}\n"
            f"Email:    {feedback.email}\n"
            f"Subject:  {feedback.subject or '—'}\n"
            f"Received: {feedback.created_at:%Y-%m-%d %H:%M UTC}\n"
            f"Attachment: {feedback.attachment_name or 'none'}\n"
            f"\n"
            f"Message:\n{feedback.message}\n"
        )
        await send_email(
            to=recipients,
            subject=subject,
            body=body,
            reply_to=feedback.email,
        )

    @staticmethod
    def _decoy(
        *, name: str, email: str, category: str, subject: str | None, message: str
    ) -> Feedback:
        """A transient, unsaved row returned to a honeypot-tripping client."""
        try:
            parsed = FeedbackCategory(category)
        except ValueError:
            parsed = FeedbackCategory.GENERAL
        return Feedback(
            id=uuid.uuid4(),
            name=name.strip(),
            email=email.strip().lower(),
            subject=(subject or None),
            category=parsed,
            message=message.strip(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
