"""Authentication service: register, login, token refresh."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.exceptions.base import ConflictError, UnauthorizedError
from app.logging import get_logger
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import TokenPair

logger = get_logger(__name__)


def _token_pair(user_id: uuid.UUID) -> TokenPair:
    settings = get_settings()
    return TokenPair(
        access_token=create_token(user_id, "access"),
        refresh_token=create_token(user_id, "refresh"),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def register(
        self, *, name: str, email: str, password: str
    ) -> tuple[User, TokenPair]:
        if await self.users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists.")
        user = User(
            name=name.strip(),
            email=email.strip().lower(),
            password_hash=hash_password(password),
        )
        self.users.add(user)
        await self.session.commit()
        logger.info("user_registered", user_id=str(user.id))
        return user, _token_pair(user.id)

    async def login(self, *, email: str, password: str) -> tuple[User, TokenPair]:
        user = await self.users.get_by_email(email)
        # Constant-shape failure: never reveal whether the email exists.
        if user is None or not verify_password(password, user.password_hash):
            raise UnauthorizedError("Invalid email or password.")
        logger.info("user_logged_in", user_id=str(user.id))
        return user, _token_pair(user.id)

    async def refresh(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, expected_type="refresh")
        if payload is None:
            raise UnauthorizedError("Invalid or expired refresh token.")
        user = await self.users.get(uuid.UUID(payload["sub"]))
        if user is None:
            raise UnauthorizedError("Account no longer exists.")
        return _token_pair(user.id)
