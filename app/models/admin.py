"""Admin-panel models.

These tables back the admin panel's own features — settings, CMS content,
audit trail, tool configuration, subscriptions and captured error logs. They
are additive and fully isolated from the user-facing tables (``users``,
``stored_files``, ``processing_jobs``, ``feedback``), which the admin panel
reads through the existing repositories/services.

Status/level columns use plain ``String`` (validated at the schema layer)
rather than PostgreSQL enums to keep the admin migration self-contained and
easy to evolve as new content states are introduced.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import (
    AdminLogCategory,
    ContentStatus,
    ErrorLogLevel,
    SubscriptionStatus,
    UserStatus,
)
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class AdminAuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An immutable record of an admin action (Audit Logs + Security Events).

    ``category`` splits the feed into the two monitoring views: routine
    administrative actions (``audit``) and security-relevant events
    (``security``) such as failed logins and rate-limit trips.
    """

    __tablename__ = "admin_audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Denormalised so the log survives (and stays readable) after the account
    # is deleted.
    actor_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    category: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AdminLogCategory.AUDIT,
        server_default="audit",
        index=True,
    )
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("ix_admin_audit_logs_created_at", "created_at"),
    )


class AppSetting(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single platform setting, stored as a typed JSON value.

    The settings pages read/write these key/value rows grouped by
    ``category`` (general, auth, email, uploads, razorpay, security, backup,
    localization, integrations, branding, seo).
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True, index=True
    )
    value: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, default="general", server_default="general"
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class ToolConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Admin-controlled configuration + display metadata for a PDF tool.

    Seeded from the canonical :class:`app.constants.ToolSlug` list; the admin
    can enable/disable, hide, set maintenance mode, and cap file size per
    tool. Usage counts are computed live from ``processing_jobs``.
    """

    __tablename__ = "tool_configs"

    slug: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="Other", server_default="Other"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    maintenance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    file_limit_mb: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class Announcement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A platform-wide announcement (Announcements page)."""

    __tablename__ = "announcements"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContentStatus.DRAFT, server_default="draft"
    )
    audience: Mapped[str] = mapped_column(
        String(32), nullable=False, default="all", server_default="all"
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Faq(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A frequently-asked question managed from the admin FAQs page."""

    __tablename__ = "faqs"

    question: Mapped[str] = mapped_column(String(300), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class BlogPost(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A blog article managed from the admin Blog page."""

    __tablename__ = "blog_posts"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(220), nullable=False, unique=True, index=True
    )
    excerpt: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContentStatus.DRAFT, server_default="draft"
    )
    cover_image: Mapped[str | None] = mapped_column(String(512), nullable=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    views: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ContentPage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A managed static/content page (Pages & Content)."""

    __tablename__ = "content_pages"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(220), nullable=False, unique=True, index=True
    )
    path: Mapped[str] = mapped_column(String(220), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ContentStatus.PUBLISHED,
        server_default="published",
    )
    meta_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ContactMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A message submitted through the public contact form (Messages page)."""

    __tablename__ = "contact_messages"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_contact_messages_created_at", "created_at"),
    )


class Subscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A subscriber's plan record (Subscribers page).

    There is no live payment integration; these rows are the source of truth
    for the Subscribers screen and are created/edited by admins (or, in the
    future, by a Razorpay webhook).
    """

    __tablename__ = "subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan: Mapped[str] = mapped_column(String(64), nullable=False)
    price_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="USD", server_default="USD"
    )
    interval: Mapped[str] = mapped_column(
        String(16), nullable=False, default="monthly", server_default="monthly"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=SubscriptionStatus.ACTIVE,
        server_default="active",
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="razorpay", server_default="razorpay"
    )
    provider_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    renews_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payments_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class ErrorLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A captured application error/warning (Error Logs page).

    The catch-all exception handler writes here best-effort; entries are
    de-duplicated by ``fingerprint`` and their occurrence ``count`` is
    incremented instead of inserting duplicates.
    """

    __tablename__ = "error_logs"

    level: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ErrorLogLevel.ERROR, server_default="error"
    )
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    service: Mapped[str | None] = mapped_column(String(64), nullable=True)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stack: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    resolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_error_logs_created_at", "created_at"),
    )
