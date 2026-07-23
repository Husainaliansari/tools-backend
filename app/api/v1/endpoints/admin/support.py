"""Admin feedback & contact-message endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.endpoints.admin._common import PageParamsDep, ok, paged
from app.common.pagination import Page
from app.dependencies.admin import AdminUserDep
from app.dependencies.services import AdminServiceDep
from app.schemas.admin import (
    AdminFeedbackRow,
    ContactMessageRow,
    MessageReply,
)
from app.schemas.response import SuccessResponse

router = APIRouter(tags=["Admin: Support"])


# ── Feedback ─────────────────────────────────────────────────────────────
@router.get("/feedback", response_model=SuccessResponse[Page[AdminFeedbackRow]])
async def list_feedback(
    service: AdminServiceDep,
    params: PageParamsDep,
    category: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[AdminFeedbackRow]]:
    rows, total = await service.list_feedback(page=params, category=category, q=q)
    return paged([AdminFeedbackRow(**r) for r in rows], total, params)


@router.get("/feedback/stats", response_model=SuccessResponse[dict])
async def feedback_stats(service: AdminServiceDep) -> SuccessResponse[dict]:
    return ok(await service.feedback_stats())


@router.delete("/feedback/{fb_id}", response_model=SuccessResponse[None])
async def delete_feedback(
    fb_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[None]:
    await service.delete_feedback(fb_id)
    await service.audit(
        actor=admin, action="feedback.delete", summary="Deleted feedback",
        entity_type="feedback", entity_id=str(fb_id),
    )
    return ok(None, "Feedback deleted.")


# ── Contact messages ─────────────────────────────────────────────────────
@router.get("/messages", response_model=SuccessResponse[Page[ContactMessageRow]])
async def list_messages(
    service: AdminServiceDep,
    params: PageParamsDep,
    q: Annotated[str | None, Query()] = None,
    unread: Annotated[bool | None, Query()] = None,
) -> SuccessResponse[Page[ContactMessageRow]]:
    rows, total = await service.list_messages(page=params, q=q, unread=unread)
    return paged([ContactMessageRow(**r) for r in rows], total, params)


@router.get("/messages/unread-count", response_model=SuccessResponse[dict])
async def unread_count(service: AdminServiceDep) -> SuccessResponse[dict]:
    return ok({"count": await service.unread_message_count()})


@router.get("/messages/{msg_id}", response_model=SuccessResponse[ContactMessageRow])
async def get_message(
    msg_id: uuid.UUID, service: AdminServiceDep
) -> SuccessResponse[ContactMessageRow]:
    # A GET is side-effect free: reading a message must not mutate it. The
    # frontend marks a message read via the explicit endpoint below.
    m = await service.get_message(msg_id)
    return ok(ContactMessageRow(**service._message_row(m)))


@router.post("/messages/{msg_id}/read", response_model=SuccessResponse[ContactMessageRow])
async def mark_message_read(
    msg_id: uuid.UUID,
    service: AdminServiceDep,
    admin: AdminUserDep,
    read: Annotated[bool, Query()] = True,
) -> SuccessResponse[ContactMessageRow]:
    m = await service.mark_message_read(msg_id, read)
    return ok(ContactMessageRow(**service._message_row(m)))


@router.post("/messages/{msg_id}/reply", response_model=SuccessResponse[ContactMessageRow])
async def reply_message(
    msg_id: uuid.UUID,
    payload: MessageReply,
    service: AdminServiceDep,
    admin: AdminUserDep,
) -> SuccessResponse[ContactMessageRow]:
    m = await service.reply_message(msg_id, payload.reply)
    await service.audit(
        actor=admin, action="message.reply", summary=f"Replied to {m.email}",
        entity_type="message", entity_id=str(m.id),
    )
    return ok(ContactMessageRow(**service._message_row(m)), "Reply sent.")


@router.delete("/messages/{msg_id}", response_model=SuccessResponse[None])
async def delete_message(
    msg_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[None]:
    await service.delete_message(msg_id)
    await service.audit(
        actor=admin, action="message.delete", summary="Deleted message",
        entity_type="message", entity_id=str(msg_id),
    )
    return ok(None, "Message deleted.")
