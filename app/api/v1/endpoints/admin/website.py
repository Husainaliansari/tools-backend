"""Admin website-content endpoints: announcements, FAQs, blog, pages."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.endpoints.admin._common import PageParamsDep, ok, paged
from app.common.pagination import Page
from app.dependencies.admin import AdminUserDep
from app.dependencies.services import AdminServiceDep
from app.schemas.admin import (
    AnnouncementRow,
    AnnouncementUpsert,
    BlogPostRow,
    BlogPostUpsert,
    ContentPageRow,
    ContentPageUpsert,
    FaqRow,
    FaqUpsert,
)
from app.schemas.response import SuccessResponse

router = APIRouter(tags=["Admin: Website"])


# ── Announcements ────────────────────────────────────────────────────────
@router.get("/announcements", response_model=SuccessResponse[Page[AnnouncementRow]])
async def list_announcements(
    service: AdminServiceDep,
    params: PageParamsDep,
    q: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[AnnouncementRow]]:
    rows, total = await service.list_announcements(page=params, q=q)
    return paged([AnnouncementRow.model_validate(r) for r in rows], total, params)


@router.post("/announcements", response_model=SuccessResponse[AnnouncementRow], status_code=201)
async def create_announcement(
    payload: AnnouncementUpsert, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[AnnouncementRow]:
    ann = await service.create_announcement(payload, admin)
    await service.audit(
        actor=admin, action="announcement.create", summary=f"Created '{ann.title}'",
        entity_type="announcement", entity_id=str(ann.id),
    )
    return ok(AnnouncementRow.model_validate(ann), "Announcement created.")


@router.patch("/announcements/{ann_id}", response_model=SuccessResponse[AnnouncementRow])
async def update_announcement(
    ann_id: uuid.UUID,
    payload: AnnouncementUpsert,
    service: AdminServiceDep,
    admin: AdminUserDep,
) -> SuccessResponse[AnnouncementRow]:
    ann = await service.update_announcement(ann_id, payload)
    await service.audit(
        actor=admin, action="announcement.update", summary=f"Updated '{ann.title}'",
        entity_type="announcement", entity_id=str(ann.id),
    )
    return ok(AnnouncementRow.model_validate(ann), "Announcement updated.")


@router.delete("/announcements/{ann_id}", response_model=SuccessResponse[None])
async def delete_announcement(
    ann_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[None]:
    await service.delete_announcement(ann_id)
    await service.audit(
        actor=admin, action="announcement.delete", summary="Deleted announcement",
        entity_type="announcement", entity_id=str(ann_id),
    )
    return ok(None, "Announcement deleted.")


# ── FAQs ─────────────────────────────────────────────────────────────────
@router.get("/faqs", response_model=SuccessResponse[Page[FaqRow]])
async def list_faqs(
    service: AdminServiceDep,
    params: PageParamsDep,
    q: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[FaqRow]]:
    rows, total = await service.list_faqs(page=params, q=q)
    return paged([FaqRow.model_validate(r) for r in rows], total, params)


@router.post("/faqs", response_model=SuccessResponse[FaqRow], status_code=201)
async def create_faq(
    payload: FaqUpsert, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[FaqRow]:
    faq = await service.create_faq(payload)
    await service.audit(
        actor=admin, action="faq.create", summary="Created FAQ",
        entity_type="faq", entity_id=str(faq.id),
    )
    return ok(FaqRow.model_validate(faq), "FAQ created.")


@router.patch("/faqs/{faq_id}", response_model=SuccessResponse[FaqRow])
async def update_faq(
    faq_id: uuid.UUID, payload: FaqUpsert, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[FaqRow]:
    faq = await service.update_faq(faq_id, payload)
    await service.audit(
        actor=admin, action="faq.update", summary="Updated FAQ",
        entity_type="faq", entity_id=str(faq.id),
    )
    return ok(FaqRow.model_validate(faq), "FAQ updated.")


@router.delete("/faqs/{faq_id}", response_model=SuccessResponse[None])
async def delete_faq(
    faq_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[None]:
    await service.delete_faq(faq_id)
    await service.audit(
        actor=admin, action="faq.delete", summary="Deleted FAQ",
        entity_type="faq", entity_id=str(faq_id),
    )
    return ok(None, "FAQ deleted.")


# ── Blog ─────────────────────────────────────────────────────────────────
@router.get("/blog", response_model=SuccessResponse[Page[BlogPostRow]])
async def list_blog(
    service: AdminServiceDep,
    params: PageParamsDep,
    q: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[BlogPostRow]]:
    rows, total = await service.list_blog(page=params, q=q)
    return paged([BlogPostRow.model_validate(r) for r in rows], total, params)


@router.post("/blog", response_model=SuccessResponse[BlogPostRow], status_code=201)
async def create_blog(
    payload: BlogPostUpsert, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[BlogPostRow]:
    post = await service.create_blog(payload, admin)
    await service.audit(
        actor=admin, action="blog.create", summary=f"Created post '{post.title}'",
        entity_type="blog", entity_id=str(post.id),
    )
    return ok(BlogPostRow.model_validate(post), "Post created.")


@router.patch("/blog/{post_id}", response_model=SuccessResponse[BlogPostRow])
async def update_blog(
    post_id: uuid.UUID,
    payload: BlogPostUpsert,
    service: AdminServiceDep,
    admin: AdminUserDep,
) -> SuccessResponse[BlogPostRow]:
    post = await service.update_blog(post_id, payload)
    await service.audit(
        actor=admin, action="blog.update", summary=f"Updated post '{post.title}'",
        entity_type="blog", entity_id=str(post.id),
    )
    return ok(BlogPostRow.model_validate(post), "Post updated.")


@router.delete("/blog/{post_id}", response_model=SuccessResponse[None])
async def delete_blog(
    post_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[None]:
    await service.delete_blog(post_id)
    await service.audit(
        actor=admin, action="blog.delete", summary="Deleted post",
        entity_type="blog", entity_id=str(post_id),
    )
    return ok(None, "Post deleted.")


# ── Pages ────────────────────────────────────────────────────────────────
@router.get("/pages", response_model=SuccessResponse[Page[ContentPageRow]])
async def list_pages(
    service: AdminServiceDep,
    params: PageParamsDep,
    q: Annotated[str | None, Query()] = None,
) -> SuccessResponse[Page[ContentPageRow]]:
    rows, total = await service.list_pages(page=params, q=q)
    return paged([ContentPageRow.model_validate(r) for r in rows], total, params)


@router.post("/pages", response_model=SuccessResponse[ContentPageRow], status_code=201)
async def create_page(
    payload: ContentPageUpsert, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[ContentPageRow]:
    page = await service.create_page(payload)
    await service.audit(
        actor=admin, action="page.create", summary=f"Created page '{page.title}'",
        entity_type="page", entity_id=str(page.id),
    )
    return ok(ContentPageRow.model_validate(page), "Page created.")


@router.patch("/pages/{page_id}", response_model=SuccessResponse[ContentPageRow])
async def update_page(
    page_id: uuid.UUID,
    payload: ContentPageUpsert,
    service: AdminServiceDep,
    admin: AdminUserDep,
) -> SuccessResponse[ContentPageRow]:
    page = await service.update_page(page_id, payload)
    await service.audit(
        actor=admin, action="page.update", summary=f"Updated page '{page.title}'",
        entity_type="page", entity_id=str(page.id),
    )
    return ok(ContentPageRow.model_validate(page), "Page updated.")


@router.delete("/pages/{page_id}", response_model=SuccessResponse[None])
async def delete_page(
    page_id: uuid.UUID, service: AdminServiceDep, admin: AdminUserDep
) -> SuccessResponse[None]:
    await service.delete_page(page_id)
    await service.audit(
        actor=admin, action="page.delete", summary="Deleted page",
        entity_type="page", entity_id=str(page_id),
    )
    return ok(None, "Page deleted.")
