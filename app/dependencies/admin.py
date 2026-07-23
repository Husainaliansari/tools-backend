"""Admin authorization dependency.

Wraps the existing authenticated-user dependency and additionally requires the
``is_admin`` flag. Non-admins (and anonymous callers) are rejected before any
admin endpoint body runs, so the whole admin router can be guarded with a
single ``dependencies=[Depends(get_current_admin)]``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.dependencies.auth import CurrentUserDep
from app.exceptions.base import ForbiddenError
from app.models.user import User


async def get_current_admin(user: CurrentUserDep) -> User:
    if not getattr(user, "is_admin", False):
        raise ForbiddenError("Administrator access is required.")
    return user


AdminUserDep = Annotated[User, Depends(get_current_admin)]
