"""Admin panel: user role/status columns + admin tables.

Adds the ``is_admin``/``status`` columns to ``users`` and the admin-panel
tables (settings, tool config, CMS content, subscriptions, contact messages,
audit log, error log). Everything here is additive and does not alter existing
user-facing tables beyond the two nullable-with-default user columns.

Revision ID: b8e5c1a2d3f4
Revises: a7d4f2c8b9e1
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b8e5c1a2d3f4"
down_revision = "a7d4f2c8b9e1"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # users: admin role + account status (additive, backfilled by default)
    # ------------------------------------------------------------------ #
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="active",
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------ #
    # admin_audit_logs
    # ------------------------------------------------------------------ #
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_email", sa.String(length=254), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column(
            "category",
            sa.String(length=16),
            server_default="audit",
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_admin_audit_logs_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_audit_logs")),
    )
    op.create_index(
        op.f("ix_admin_audit_logs_actor_id"),
        "admin_audit_logs",
        ["actor_id"],
    )
    op.create_index(
        op.f("ix_admin_audit_logs_action"), "admin_audit_logs", ["action"]
    )
    op.create_index(
        op.f("ix_admin_audit_logs_category"), "admin_audit_logs", ["category"]
    )
    op.create_index(
        "ix_admin_audit_logs_created_at", "admin_audit_logs", ["created_at"]
    )

    # ------------------------------------------------------------------ #
    # app_settings
    # ------------------------------------------------------------------ #
    op.create_table(
        "app_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column(
            "value", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        sa.Column(
            "category",
            sa.String(length=64),
            server_default="general",
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_app_settings_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_settings")),
    )
    op.create_index(
        op.f("ix_app_settings_key"), "app_settings", ["key"], unique=True
    )

    # ------------------------------------------------------------------ #
    # tool_configs
    # ------------------------------------------------------------------ #
    op.create_table(
        "tool_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "category", sa.String(length=32), server_default="Other", nullable=False
        ),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "visible", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "maintenance",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "file_limit_mb", sa.Integer(), server_default="100", nullable=False
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_configs")),
    )
    op.create_index(
        op.f("ix_tool_configs_slug"), "tool_configs", ["slug"], unique=True
    )

    # ------------------------------------------------------------------ #
    # announcements
    # ------------------------------------------------------------------ #
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="draft", nullable=False
        ),
        sa.Column(
            "audience", sa.String(length=32), server_default="all", nullable=False
        ),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_announcements_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_announcements")),
    )

    # ------------------------------------------------------------------ #
    # faqs
    # ------------------------------------------------------------------ #
    op.create_table(
        "faqs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question", sa.String(length=300), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "published", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faqs")),
    )

    # ------------------------------------------------------------------ #
    # blog_posts
    # ------------------------------------------------------------------ #
    op.create_table(
        "blog_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("excerpt", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status", sa.String(length=16), server_default="draft", nullable=False
        ),
        sa.Column("cover_image", sa.String(length=512), nullable=True),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("views", sa.Integer(), server_default="0", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_blog_posts_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blog_posts")),
    )
    op.create_index(
        op.f("ix_blog_posts_slug"), "blog_posts", ["slug"], unique=True
    )

    # ------------------------------------------------------------------ #
    # content_pages
    # ------------------------------------------------------------------ #
    op.create_table(
        "content_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("path", sa.String(length=220), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="published",
            nullable=False,
        ),
        sa.Column("meta_title", sa.String(length=200), nullable=True),
        sa.Column("meta_description", sa.String(length=500), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_pages")),
    )
    op.create_index(
        op.f("ix_content_pages_slug"), "content_pages", ["slug"], unique=True
    )

    # ------------------------------------------------------------------ #
    # contact_messages
    # ------------------------------------------------------------------ #
    op.create_table(
        "contact_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "is_read", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_contact_messages_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_messages")),
    )
    op.create_index(
        op.f("ix_contact_messages_email"), "contact_messages", ["email"]
    )
    op.create_index(
        "ix_contact_messages_created_at", "contact_messages", ["created_at"]
    )

    # ------------------------------------------------------------------ #
    # subscriptions
    # ------------------------------------------------------------------ #
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan", sa.String(length=64), nullable=False),
        sa.Column("price_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "currency", sa.String(length=8), server_default="USD", nullable=False
        ),
        sa.Column(
            "interval",
            sa.String(length=16),
            server_default="monthly",
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
        sa.Column(
            "provider",
            sa.String(length=32),
            server_default="razorpay",
            nullable=False,
        ),
        sa.Column("provider_ref", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("renews_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payments_count", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(
        op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"]
    )

    # ------------------------------------------------------------------ #
    # error_logs
    # ------------------------------------------------------------------ #
    op.create_table(
        "error_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "level", sa.String(length=16), server_default="error", nullable=False
        ),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("service", sa.String(length=64), nullable=True),
        sa.Column("path", sa.String(length=255), nullable=True),
        sa.Column("stack", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("count", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "resolved", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_error_logs")),
    )
    op.create_index(
        op.f("ix_error_logs_fingerprint"), "error_logs", ["fingerprint"]
    )
    op.create_index("ix_error_logs_created_at", "error_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_error_logs_created_at", table_name="error_logs")
    op.drop_index(op.f("ix_error_logs_fingerprint"), table_name="error_logs")
    op.drop_table("error_logs")

    op.drop_index(op.f("ix_subscriptions_user_id"), table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index(
        "ix_contact_messages_created_at", table_name="contact_messages"
    )
    op.drop_index(
        op.f("ix_contact_messages_email"), table_name="contact_messages"
    )
    op.drop_table("contact_messages")

    op.drop_index(op.f("ix_content_pages_slug"), table_name="content_pages")
    op.drop_table("content_pages")

    op.drop_index(op.f("ix_blog_posts_slug"), table_name="blog_posts")
    op.drop_table("blog_posts")

    op.drop_table("faqs")
    op.drop_table("announcements")

    op.drop_index(op.f("ix_tool_configs_slug"), table_name="tool_configs")
    op.drop_table("tool_configs")

    op.drop_index(op.f("ix_app_settings_key"), table_name="app_settings")
    op.drop_table("app_settings")

    op.drop_index(
        "ix_admin_audit_logs_created_at", table_name="admin_audit_logs"
    )
    op.drop_index(
        op.f("ix_admin_audit_logs_category"), table_name="admin_audit_logs"
    )
    op.drop_index(
        op.f("ix_admin_audit_logs_action"), table_name="admin_audit_logs"
    )
    op.drop_index(
        op.f("ix_admin_audit_logs_actor_id"), table_name="admin_audit_logs"
    )
    op.drop_table("admin_audit_logs")

    op.drop_column("users", "status")
    op.drop_column("users", "is_admin")
