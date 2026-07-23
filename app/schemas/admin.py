"""Admin panel API schemas.

Read models and request payloads for every admin module. List endpoints return
these inside ``SuccessResponse[Page[...]]``; detail/mutation endpoints return
the single-object variants.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import EmailStr, Field

from app.schemas.base import BaseSchema, ORMSchema

# ─────────────────────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────────────────────


class AdminUserRow(ORMSchema):
    id: uuid.UUID
    name: str
    email: str
    plan: str = "free"
    status: str = "active"
    is_admin: bool = False
    avatar: str | None = None
    conversions: int = 0
    created_at: datetime
    updated_at: datetime


class AdminUserDetail(AdminUserRow):
    email_verified_at: datetime | None = None
    files_count: int = 0
    subscription: SubscriptionRow | None = None


class AdminUserCreate(BaseSchema):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    plan: str = "free"
    is_admin: bool = False


class AdminUserUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    plan: str | None = None
    status: str | None = None
    is_admin: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class BulkUserAction(BaseSchema):
    ids: list[uuid.UUID] = Field(..., min_length=1)
    action: str  # suspend | activate | delete


# ─────────────────────────────────────────────────────────────────────────────
# Subscribers
# ─────────────────────────────────────────────────────────────────────────────


class SubscriptionRow(ORMSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str | None = None
    user_email: str | None = None
    plan: str
    price_cents: int = 0
    currency: str = "USD"
    interval: str = "monthly"
    status: str = "active"
    provider: str = "razorpay"
    started_at: datetime | None = None
    renews_at: datetime | None = None
    payments_count: int = 0
    created_at: datetime


class SubscriptionCreate(BaseSchema):
    user_id: uuid.UUID
    plan: str = Field(..., min_length=1, max_length=64)
    price_cents: int = 0
    currency: str = "USD"
    interval: str = "monthly"
    status: str = "active"
    renews_at: datetime | None = None


class SubscriptionUpdate(BaseSchema):
    plan: str | None = None
    price_cents: int | None = None
    interval: str | None = None
    status: str | None = None
    renews_at: datetime | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Tools
# ─────────────────────────────────────────────────────────────────────────────


class ToolConfigRow(ORMSchema):
    id: uuid.UUID
    slug: str
    name: str
    category: str
    enabled: bool
    visible: bool
    maintenance: bool
    file_limit_mb: int
    usage: int = 0


class ToolConfigUpdate(BaseSchema):
    enabled: bool | None = None
    visible: bool | None = None
    maintenance: bool | None = None
    file_limit_mb: int | None = Field(default=None, ge=1, le=100_000)


# ─────────────────────────────────────────────────────────────────────────────
# Files & Jobs
# ─────────────────────────────────────────────────────────────────────────────


class AdminFileRow(ORMSchema):
    id: uuid.UUID
    original_name: str
    category: str
    media_type: str
    size_bytes: int
    status: str
    owner_email: str | None = None
    tool: str | None = None
    created_at: datetime
    expires_at: datetime | None = None


class AdminJobRow(ORMSchema):
    id: uuid.UUID
    tool: str
    status: str
    progress: int
    file_name: str | None = None
    user_email: str | None = None
    created_at: datetime
    error_code: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Feedback & Messages
# ─────────────────────────────────────────────────────────────────────────────


class AdminFeedbackRow(ORMSchema):
    id: uuid.UUID
    name: str
    email: str
    subject: str | None = None
    category: str
    message: str
    has_attachment: bool = False
    created_at: datetime


class ContactMessageRow(ORMSchema):
    id: uuid.UUID
    name: str
    email: str
    subject: str | None = None
    message: str
    is_read: bool = False
    reply: str | None = None
    replied_at: datetime | None = None
    created_at: datetime


class ContactMessageCreate(BaseSchema):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    subject: str | None = Field(default=None, max_length=200)
    message: str = Field(..., min_length=1)


class MessageReply(BaseSchema):
    reply: str = Field(..., min_length=1)


# ─────────────────────────────────────────────────────────────────────────────
# Announcements / Website content
# ─────────────────────────────────────────────────────────────────────────────


class AnnouncementRow(ORMSchema):
    id: uuid.UUID
    title: str
    body: str
    status: str
    audience: str
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AnnouncementUpsert(BaseSchema):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1)
    status: str = "draft"
    audience: str = "all"


class FaqRow(ORMSchema):
    id: uuid.UUID
    question: str
    answer: str
    category: str | None = None
    sort_order: int = 0
    published: bool = True
    created_at: datetime


class FaqUpsert(BaseSchema):
    question: str = Field(..., min_length=1, max_length=300)
    answer: str = Field(..., min_length=1)
    category: str | None = None
    sort_order: int = 0
    published: bool = True


class BlogPostRow(ORMSchema):
    id: uuid.UUID
    title: str
    slug: str
    excerpt: str | None = None
    content: str = ""
    status: str
    cover_image: str | None = None
    views: int = 0
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BlogPostUpsert(BaseSchema):
    title: str = Field(..., min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=220)
    excerpt: str | None = Field(default=None, max_length=500)
    content: str = ""
    status: str = "draft"
    cover_image: str | None = None


class ContentPageRow(ORMSchema):
    id: uuid.UUID
    title: str
    slug: str
    path: str
    content: str | None = None
    status: str
    meta_title: str | None = None
    meta_description: str | None = None
    created_at: datetime
    updated_at: datetime


class ContentPageUpsert(BaseSchema):
    title: str = Field(..., min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=220)
    path: str = Field(..., min_length=1, max_length=220)
    content: str | None = None
    status: str = "published"
    meta_title: str | None = None
    meta_description: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Monitoring / Logs
# ─────────────────────────────────────────────────────────────────────────────


class AuditLogRow(ORMSchema):
    id: uuid.UUID
    actor_email: str | None = None
    action: str
    category: str
    entity_type: str | None = None
    entity_id: str | None = None
    summary: str
    ip: str | None = None
    created_at: datetime


class ErrorLogRow(ORMSchema):
    id: uuid.UUID
    level: str
    message: str
    service: str | None = None
    path: str | None = None
    count: int = 1
    resolved: bool = False
    last_seen_at: datetime | None = None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────────────────────────────────────


class SettingUpdate(BaseSchema):
    value: dict[str, Any]


# Resolve the forward reference from AdminUserDetail -> SubscriptionRow.
AdminUserDetail.model_rebuild()
