"""Feedback & suggestions endpoints.

Public (no authentication required): a visitor fetches a captcha challenge,
then submits the form as ``multipart/form-data`` so it can carry an optional
screenshot. Spam is deterred by a per-IP rate limit, a hidden honeypot field,
a math captcha and a once-per-day limit (see :mod:`app.services.feedback`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from app.config import get_settings
from app.core.context import get_request_id
from app.dependencies.auth import OptionalUserIdDep
from app.dependencies.rate_limit import feedback_rate_limit
from app.dependencies.services import FeedbackServiceDep
from app.schemas.feedback import CaptchaChallenge, FeedbackOut
from app.schemas.response import SuccessResponse
from app.services import captcha
from app.services.feedback import Attachment, validate_attachment

router = APIRouter(prefix="/feedback", tags=["Feedback"])


@router.get(
    "/captcha",
    response_model=SuccessResponse[CaptchaChallenge],
    summary="Get a captcha challenge for the feedback form",
)
async def get_captcha() -> SuccessResponse[CaptchaChallenge]:
    token, question, expires_in = captcha.issue_challenge()
    return SuccessResponse(
        data=CaptchaChallenge(
            token=token, question=question, expires_in=expires_in
        ),
        request_id=get_request_id(),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[FeedbackOut],
    summary="Submit feedback, a bug report or a suggestion",
    dependencies=[Depends(feedback_rate_limit)],
)
async def submit_feedback(
    request: Request,
    service: FeedbackServiceDep,
    user_id: OptionalUserIdDep,
    name: Annotated[str, Form(min_length=1, max_length=120)],
    email: Annotated[str, Form(min_length=3, max_length=254)],
    message: Annotated[str, Form(min_length=1, max_length=5000)],
    category: Annotated[str, Form()] = "general",
    subject: Annotated[str | None, Form(max_length=200)] = None,
    captcha_token: Annotated[str, Form()] = "",
    captcha_answer: Annotated[str, Form()] = "",
    # Hidden anti-bot field; real users never see or fill it.
    website: Annotated[str | None, Form()] = None,
    attachment: Annotated[UploadFile | None, File()] = None,
) -> SuccessResponse[FeedbackOut]:
    parsed_attachment: Attachment | None = None
    if attachment is not None and attachment.filename:
        settings = get_settings()
        # Read at most one byte past the cap so oversize files fail fast
        # without buffering an unbounded amount into memory.
        data = await attachment.read(settings.FEEDBACK_ATTACHMENT_MAX_BYTES + 1)
        parsed_attachment = validate_attachment(
            filename=attachment.filename,
            content_type=attachment.content_type,
            data=data,
        )

    feedback = await service.submit(
        name=name,
        email=email,
        message=message,
        category=category,
        subject=subject,
        captcha_token=captcha_token,
        captcha_answer=captcha_answer,
        honeypot=website,
        attachment=parsed_attachment,
        client_ip=request.client.host if request.client else None,
        user_id=user_id,
    )
    return SuccessResponse(
        data=FeedbackOut.model_validate(feedback),
        message="Thanks for your feedback! We’ve received it.",
        request_id=get_request_id(),
    )
