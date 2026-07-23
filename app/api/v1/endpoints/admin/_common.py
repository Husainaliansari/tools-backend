"""Shared helpers for admin endpoint modules."""

from __future__ import annotations

from typing import Annotated, TypeVar

from fastapi import Depends, Request

from app.common.pagination import Page
from app.core.context import get_request_id
from app.dependencies.pagination import PaginationParams, pagination_params
from app.schemas.response import SuccessResponse

T = TypeVar("T")

PageParamsDep = Annotated[PaginationParams, Depends(pagination_params)]


def ok(data: T, message: str | None = None) -> SuccessResponse[T]:
    return SuccessResponse(data=data, message=message, request_id=get_request_id())


def paged(
    items: list[T], total: int, params: PaginationParams
) -> SuccessResponse[Page[T]]:
    return SuccessResponse(
        data=Page.create(items, total, params.page, params.size),
        request_id=get_request_id(),
    )


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
