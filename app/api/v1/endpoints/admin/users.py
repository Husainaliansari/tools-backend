"""Admin user-management endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.v1.endpoints.admin._common import PageParamsDep, client_ip, ok, paged
from app.common.pagination import Page
from app.dependencies.admin import AdminUserDep
from app.dependencies.services import AdminServiceDep
from app.exceptions.base import BadRequestError
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserDetail,
    AdminUserRow,
    AdminUserUpdate,
    BulkUserAction,
)
from app.schemas.response import SuccessResponse

router = APIRouter(prefix="/users", tags=["Admin: Users"])


@router.get("", response_model=SuccessResponse[Page[AdminUserRow]])
async def list_users(
    service: AdminServiceDep,
    params: PageParamsDep,
    q: Annotated[str | None, Query()] = None,
    plan: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    sort: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[AdminUserRow]]:
    rows, total = await service.list_users(
        page=params, q=q, plan=plan, status=status, sort=sort
    )
    return paged([AdminUserRow(**r) for r in rows], total, params)


@router.get("/stats", response_model=SuccessResponse[dict])
async def user_stats(service: AdminServiceDep) -> SuccessResponse[dict]:
    return ok(await service.user_stats())


@router.get("/{user_id}", response_model=SuccessResponse[AdminUserDetail])
async def get_user(
    user_id: uuid.UUID, service: AdminServiceDep
) -> SuccessResponse[AdminUserDetail]:
    return ok(AdminUserDetail(**await service.user_detail(user_id)))


@router.post("", response_model=SuccessResponse[AdminUserDetail], status_code=201)
async def create_user(
    payload: AdminUserCreate,
    service: AdminServiceDep,
    admin: AdminUserDep,
    request: Request,
) -> SuccessResponse[AdminUserDetail]:
    user = await service.create_user(payload)
    await service.audit(
        actor=admin,
        action="user.create",
        summary=f"Created user {user.email}",
        entity_type="user",
        entity_id=str(user.id),
        ip=client_ip(request),
    )
    return ok(AdminUserDetail(**await service.user_detail(user.id)), "User created.")


@router.patch("/{user_id}", response_model=SuccessResponse[AdminUserDetail])
async def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    service: AdminServiceDep,
    admin: AdminUserDep,
    request: Request,
) -> SuccessResponse[AdminUserDetail]:
    user = await service.update_user(user_id, payload)
    await service.audit(
        actor=admin,
        action="user.update",
        summary=f"Updated user {user.email}",
        entity_type="user",
        entity_id=str(user.id),
        ip=client_ip(request),
    )
    return ok(AdminUserDetail(**await service.user_detail(user.id)), "User updated.")


@router.post("/{user_id}/suspend", response_model=SuccessResponse[AdminUserDetail])
async def suspend_user(
    user_id: uuid.UUID,
    service: AdminServiceDep,
    admin: AdminUserDep,
    request: Request,
) -> SuccessResponse[AdminUserDetail]:
    if user_id == admin.id:
        raise BadRequestError("You cannot suspend your own account.")
    user = await service.set_user_status(user_id, "suspended")
    await service.audit(
        actor=admin,
        action="user.suspend",
        summary=f"Suspended user {user.email}",
        category="security",
        entity_type="user",
        entity_id=str(user.id),
        ip=client_ip(request),
    )
    return ok(AdminUserDetail(**await service.user_detail(user.id)), "User suspended.")


@router.post("/{user_id}/activate", response_model=SuccessResponse[AdminUserDetail])
async def activate_user(
    user_id: uuid.UUID,
    service: AdminServiceDep,
    admin: AdminUserDep,
    request: Request,
) -> SuccessResponse[AdminUserDetail]:
    user = await service.set_user_status(user_id, "active")
    await service.audit(
        actor=admin,
        action="user.activate",
        summary=f"Activated user {user.email}",
        entity_type="user",
        entity_id=str(user.id),
        ip=client_ip(request),
    )
    return ok(AdminUserDetail(**await service.user_detail(user.id)), "User activated.")


@router.delete("/{user_id}", response_model=SuccessResponse[None])
async def delete_user(
    user_id: uuid.UUID,
    service: AdminServiceDep,
    admin: AdminUserDep,
    request: Request,
) -> SuccessResponse[None]:
    if user_id == admin.id:
        raise BadRequestError("You cannot delete your own account.")
    user = await service.get_user(user_id)
    email = user.email
    await service.delete_user(user_id)
    await service.audit(
        actor=admin,
        action="user.delete",
        summary=f"Deleted user {email}",
        category="security",
        entity_type="user",
        entity_id=str(user_id),
        ip=client_ip(request),
    )
    return ok(None, "User deleted.")


@router.post("/bulk", response_model=SuccessResponse[dict])
async def bulk_users(
    payload: BulkUserAction,
    service: AdminServiceDep,
    admin: AdminUserDep,
    request: Request,
) -> SuccessResponse[dict]:
    if admin.id in payload.ids and payload.action in {"delete", "suspend"}:
        raise BadRequestError(
            "You cannot include your own account in a bulk suspend or delete."
        )
    count = await service.bulk_users(payload.action, payload.ids)
    await service.audit(
        actor=admin,
        action=f"user.bulk_{payload.action}",
        summary=f"Bulk {payload.action} on {count} user(s)",
        category="security",
        ip=client_ip(request),
    )
    return ok({"affected": count}, f"Applied {payload.action} to {count} user(s).")
