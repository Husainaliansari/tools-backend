"""Feedback-domain exceptions."""

from __future__ import annotations

from http import HTTPStatus

from app.constants import ErrorCode
from app.exceptions.base import AppException


class CaptchaInvalidError(AppException):
    status_code = HTTPStatus.BAD_REQUEST
    error_code = ErrorCode.CAPTCHA_INVALID
    message = "The captcha answer is incorrect or has expired. Please try again."


class FeedbackDailyLimitError(AppException):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    error_code = ErrorCode.FEEDBACK_DAILY_LIMIT
    message = "You can only submit feedback once per day. Please try again tomorrow."
