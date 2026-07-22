"""Best-effort outbound email over SMTP (standard library).

Kept intentionally small and dependency-free: it uses :mod:`smtplib` on a
worker thread so the async event loop is never blocked. When no ``SMTP_HOST``
is configured (the local-dev default) sends are logged and skipped rather than
raised — notification email is a side effect of a request, never the reason it
succeeds or fails.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import anyio

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


def _send_sync(message: EmailMessage) -> None:
    settings = get_settings()
    with smtplib.SMTP(
        settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT_SECONDS
    ) as client:
        if settings.SMTP_USE_TLS:
            client.starttls()
        if settings.SMTP_USERNAME:
            client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        client.send_message(message)


async def send_email(
    *,
    to: list[str],
    subject: str,
    body: str,
    reply_to: str | None = None,
) -> bool:
    """Send a plain-text email. Returns ``True`` if it was dispatched.

    Never raises: a missing SMTP configuration or a transport error is logged
    and reported as ``False`` so callers can proceed regardless.
    """
    settings = get_settings()
    recipients = [addr for addr in to if addr]
    if not recipients:
        return False
    if not settings.SMTP_HOST:
        logger.info(
            "email_skipped_no_smtp",
            to=recipients,
            subject=subject,
        )
        return False

    message = EmailMessage()
    message["From"] = formataddr((settings.EMAIL_FROM_NAME, settings.EMAIL_FROM))
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body)

    try:
        await anyio.to_thread.run_sync(_send_sync, message)
    except Exception as exc:  # noqa: BLE001 - notification is best-effort
        logger.warning("email_send_failed", subject=subject, error=str(exc))
        return False

    logger.info("email_sent", to=recipients, subject=subject)
    return True
