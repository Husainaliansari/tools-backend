"""Password hashing and JWT issuance/validation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.config import get_settings

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def create_token(user_id: uuid.UUID, token_type: TokenType) -> str:
    settings = get_settings()
    lifetime = (
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        if token_type == "access"  # noqa: S105 - token *kind*, not a secret
        else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any] | None:
    """Return the payload of a valid token of the expected type, else None."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type or "sub" not in payload:
        return None
    return payload
