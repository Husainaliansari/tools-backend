"""Users table and per-user ownership of files and jobs.

Revision ID: e5b2c9d0a1f3
Revises: c3a1f0e1b2d4
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e5b2c9d0a1f3"
down_revision = "c3a1f0e1b2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "plan", sa.String(length=32), nullable=False, server_default="free"
        ),
        sa.Column("avatar", sa.String(length=512), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    for table in ("stored_files", "processing_jobs"):
        op.add_column(
            table, sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True)
        )
        op.create_foreign_key(
            op.f(f"fk_{table}_user_id_users"),
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(op.f(f"ix_{table}_user_id"), table, ["user_id"], unique=False)


def downgrade() -> None:
    for table in ("processing_jobs", "stored_files"):
        op.drop_index(op.f(f"ix_{table}_user_id"), table_name=table)
        op.drop_constraint(op.f(f"fk_{table}_user_id_users"), table, type_="foreignkey")
        op.drop_column(table, "user_id")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
