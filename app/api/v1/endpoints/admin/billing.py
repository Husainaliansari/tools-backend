"""Admin subscribers / billing endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.endpoints.admin._common import PageParamsDep, ok, paged
from app.common.pagination import Page
from app.dependencies.admin import AdminUserDep
from app.dependencies.services import AdminServiceDep
from app.schemas.admin import (
    SubscriptionCreate,
    SubscriptionRow,
    SubscriptionUpdate,
)
from app.schemas.response import SuccessResponse

router = APIRouter(prefix="/subscribers", tags=["Admin: Subscribers"])


@router.get("", response_model=SuccessResponse[Page[SubscriptionRow]])
async def list_subscribers(
    service: AdminServiceDep,
    params: PageParamsDep,
    q: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    sort: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[SubscriptionRow]]:
    rows, total = await service.list_subscriptions(
        page=params, q=q, status=status, sort=sort
    )
    return paged([SubscriptionRow(**r) for r in rows], total, params)


@router.get("/stats", response_model=SuccessResponse[dict])
async def subscriber_stats(service: AdminServiceDep) -> SuccessResponse[dict]:
    return ok(await service.subscription_stats())


@router.post("", response_model=SuccessResponse[SubscriptionRow], status_code=201)
async def create_subscription(
    payload: SubscriptionCreate, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[SubscriptionRow]:
    sub = await service.create_subscription(payload)
    await service.audit(
        actor=admin,
        action="subscription.create",
        summary=f"Created subscription {sub.plan}",
        entity_type="subscription",
        entity_id=str(sub.id),
    )
    user = await service.get_user(sub.user_id)
    return ok(SubscriptionRow(**service._subscription_row(sub, user)))


@router.patch("/{sub_id}", response_model=SuccessResponse[SubscriptionRow])
async def update_subscription(
    sub_id: uuid.UUID,
    payload: SubscriptionUpdate,
    service: AdminServiceDep,
    admin: AdminUserDep,
) -> SuccessResponse[SubscriptionRow]:
    sub = await service.update_subscription(sub_id, payload)
    await service.audit(
        actor=admin,
        action="subscription.update",
        summary=f"Updated subscription {sub.plan}",
        entity_type="subscription",
        entity_id=str(sub.id),
    )
    user = await service.get_user(sub.user_id)
    return ok(SubscriptionRow(**service._subscription_row(sub, user)))


@router.delete("/{sub_id}", response_model=SuccessResponse[None])
async def delete_subscription(
    sub_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[None]:
    await service.delete_subscription(sub_id)
    await service.audit(
        actor=admin,
        action="subscription.delete",
        summary="Deleted subscription",
        entity_type="subscription",
        entity_id=str(sub_id),
    )
    return ok(None, "Subscription deleted.")
