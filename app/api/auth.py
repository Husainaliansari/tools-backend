"""Authentication endpoints (mounted at /api/auth to match the frontend).

Password-reset endpoints are acknowledged no-ops until an email provider is
configured — they respond identically whether or not the account exists.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_request_id
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.schemas.auth import (
    AuthSession,
    LoginPayload,
    RefreshPayload,
    RegisterPayload,
    TokenPair,
    UserOut,
)
from app.schemas.response import SuccessResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/api/auth", tags=["Auth"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[AuthSession],
    summary="Create an account",
)
async def register(
    payload: RegisterPayload, session: SessionDep
) -> SuccessResponse[AuthSession]:
    user, tokens = await AuthService(session).register(
        name=payload.name, email=payload.email, password=payload.password
    )
    return SuccessResponse(
        data=AuthSession(user=UserOut.model_validate(user), tokens=tokens),
        message="Account created.",
        request_id=get_request_id(),
    )


@router.post(
    "/login",
    response_model=SuccessResponse[AuthSession],
    summary="Sign in",
)
async def login(
    payload: LoginPayload, session: SessionDep
) -> SuccessResponse[AuthSession]:
    user, tokens = await AuthService(session).login(
        email=payload.email, password=payload.password
    )
    return SuccessResponse(
        data=AuthSession(user=UserOut.model_validate(user), tokens=tokens),
        request_id=get_request_id(),
    )


@router.post(
    "/refresh",
    response_model=SuccessResponse[TokenPair],
    summary="Exchange a refresh token for new tokens",
)
async def refresh(
    payload: RefreshPayload, session: SessionDep
) -> SuccessResponse[TokenPair]:
    tokens = await AuthService(session).refresh(payload.refresh_token)
    return SuccessResponse(data=tokens, request_id=get_request_id())


@router.get(
    "/me",
    response_model=SuccessResponse[UserOut],
    summary="Current account",
)
async def me(user: CurrentUserDep) -> SuccessResponse[UserOut]:
    return SuccessResponse(
        data=UserOut.model_validate(user), request_id=get_request_id()
    )


@router.post(
    "/logout",
    response_model=SuccessResponse[None],
    summary="Sign out",
    description="Stateless JWTs: the client discards its tokens.",
)
async def logout() -> SuccessResponse[None]:
    return SuccessResponse(data=None, message="Signed out.")


@router.post(
    "/forgot-password",
    response_model=SuccessResponse[None],
    summary="Request a password reset (no-op until email is configured)",
)
async def forgot_password() -> SuccessResponse[None]:
    return SuccessResponse(
        data=None,
        message="If an account exists for that email, a reset link will be sent.",
    )


@router.post(
    "/reset-password",
    response_model=SuccessResponse[None],
    summary="Reset password (no-op until email is configured)",
)
async def reset_password() -> SuccessResponse[None]:
    return SuccessResponse(data=None, message="Password reset is not available yet.")
