"""Feedback submissions table.

Revision ID: a7d4f2c8b9e1
Revises: e5b2c9d0a1f3
Create Date: 2026-07-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a7d4f2c8b9e1"
down_revision = "e5b2c9d0a1f3"
branch_labels = None
depends_on = None

feedback_category = postgresql.ENUM(
    "general",
    "bug",
    "feature",
    "ui_ux",
    "performance",
    "other",
    name="feedback_category",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    feedback_category.create(bind, checkfirst=True)

    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("category", feedback_category, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("attachment_name", sa.String(length=255), nullable=True),
        sa.Column("attachment_content_type", sa.String(length=127), nullable=True),
        sa.Column("attachment_size", sa.Integer(), nullable=True),
        sa.Column("attachment_data", sa.LargeBinary(), nullable=True),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_feedback_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )
    op.create_index(op.f("ix_feedback_email"), "feedback", ["email"], unique=False)
    op.create_index(
        op.f("ix_feedback_user_id"), "feedback", ["user_id"], unique=False
    )
    op.create_index(
        "ix_feedback_created_at", "feedback", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_created_at", table_name="feedback")
    op.drop_index(op.f("ix_feedback_user_id"), table_name="feedback")
    op.drop_index(op.f("ix_feedback_email"), table_name="feedback")
    op.drop_table("feedback")

    bind = op.get_bind()
    feedback_category.drop(bind, checkfirst=True)
