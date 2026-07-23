"""Auth API schemas (shapes mirror the frontend's auth service contract)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, model_validator

from app.schemas.base import BaseSchema, ORMSchema


class RegisterPayload(BaseSchema):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    password_confirmation: str | None = None

    @model_validator(mode="after")
    def _passwords_match(self) -> RegisterPayload:
        if (
            self.password_confirmation is not None
            and self.password_confirmation != self.password
        ):
            raise ValueError("Passwords do not match.")
        return self


class LoginPayload(BaseSchema):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class RefreshPayload(BaseSchema):
    refresh_token: str = Field(..., min_length=1)


class TokenPair(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # noqa: S105 - scheme name, not a secret
    expires_in: int


class UserOut(ORMSchema):
    id: uuid.UUID
    name: str
    email: str
    email_verified_at: datetime | None = None
    avatar: str | None = None
    plan: str = "free"
    is_admin: bool = False
    status: str = "active"
    created_at: datetime
    updated_at: datetime


class AuthSession(BaseSchema):
    """Login/register response payload: the user plus their tokens."""

    user: UserOut
    tokens: TokenPair
