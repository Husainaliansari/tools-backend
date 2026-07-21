"""Authentication dependencies.

Two levels:

* ``OptionalUserDep`` — resolves the user when a valid Bearer token is
  present; ``None`` when the request is anonymous. A *present but invalid*
  token is rejected (401) rather than silently downgraded to anonymous.
* ``CurrentUserDep`` — requires authentication.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db import get_db
from app.exceptions.base import UnauthorizedError
from app.models.user import User
from app.repositories.user import UserRepository


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


async def get_optional_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    token = bearer_token(request)
    if token is None:
        return None
    payload = decode_token(token, expected_type="access")
    if payload is None:
        raise UnauthorizedError("Invalid or expired access token.")
    user = await UserRepository(session).get(uuid.UUID(payload["sub"]))
    if user is None:
        raise UnauthorizedError("Account no longer exists.")
    return user


async def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    if user is None:
        raise UnauthorizedError()
    return user


async def get_optional_user_id(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> uuid.UUID | None:
    """The caller's user id, or ``None`` for anonymous requests.

    Most endpoints only need the id for ownership predicates — this saves
    them the ``user.id if user else None`` dance.
    """
    return user.id if user else None


OptionalUserDep = Annotated[User | None, Depends(get_optional_user)]
OptionalUserIdDep = Annotated[uuid.UUID | None, Depends(get_optional_user_id)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
