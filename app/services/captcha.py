"""Stateless, dependency-free math captcha.

A tiny anti-bot challenge that needs no external service (no reCAPTCHA keys)
and no server-side storage. The server issues a random arithmetic question and
a *signed* token that encodes the expected answer and an expiry; the client
echoes the token back with the user's answer and the server verifies the
HMAC signature and the answer. Tampering invalidates the signature; replay is
bounded by the short expiry.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


def _sign(payload: bytes) -> str:
    secret = get_settings().SECRET_KEY.encode()
    digest = hmac.new(secret, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def issue_challenge() -> tuple[str, str, int]:
    """Return ``(token, question, expires_in_seconds)`` for a fresh challenge."""
    settings = get_settings()
    ttl = settings.FEEDBACK_CAPTCHA_TTL_MINUTES * 60

    a = secrets.randbelow(9) + 1  # 1..9
    b = secrets.randbelow(9) + 1  # 1..9
    answer = a + b
    expires_at = int(time.time()) + ttl

    body = json.dumps({"a": answer, "exp": expires_at}, separators=(",", ":"))
    body_b64 = _b64encode(body.encode())
    token = f"{body_b64}.{_sign(body_b64.encode())}"
    question = f"{a} + {b} ="
    return token, question, ttl


def verify(token: str, answer: str) -> bool:
    """Return whether ``answer`` solves the challenge encoded in ``token``."""
    if not token or answer is None:
        return False
    try:
        body_b64, signature = token.split(".", 1)
    except ValueError:
        return False

    # Constant-time signature check before trusting any payload contents.
    if not hmac.compare_digest(signature, _sign(body_b64.encode())):
        return False

    try:
        payload = json.loads(_b64decode(body_b64))
        expected = int(payload["a"])
        expires_at = int(payload["exp"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return False

    if time.time() > expires_at:
        return False

    try:
        return int(str(answer).strip()) == expected
    except ValueError:
        return False
