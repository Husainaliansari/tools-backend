"""Initial tables: stored_files, processing_jobs, job_files.

Revision ID: c3a1f0e1b2d4
Revises:
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c3a1f0e1b2d4"
down_revision = None
branch_labels = None
depends_on = None

file_category = postgresql.ENUM(
    "upload", "processed", "thumbnail", name="file_category", create_type=False
)
file_status = postgresql.ENUM(
    "active", "expired", "deleted", name="file_status", create_type=False
)
job_status = postgresql.ENUM(
    "pending",
    "queued",
    "processing",
    "completed",
    "failed",
    "cancelled",
    "expired",
    name="job_status",
    create_type=False,
)
job_file_role = postgresql.ENUM(
    "input", "output", name="job_file_role", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    file_category.create(bind, checkfirst=True)
    file_status.create(bind, checkfirst=True)
    job_status.create(bind, checkfirst=True)
    job_file_role.create(bind, checkfirst=True)

    op.create_table(
        "stored_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False),
        sa.Column("category", file_category, nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=127), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", file_status, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stored_files")),
    )
    op.create_index(
        op.f("ix_stored_files_status"), "stored_files", ["status"], unique=False
    )
    op.create_index(
        "ix_stored_files_expires_at", "stored_files", ["expires_at"], unique=False
    )

    op.create_table(
        "processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("progress", sa.SmallInteger(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=155), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_jobs")),
    )
    op.create_index(
        op.f("ix_processing_jobs_tool"), "processing_jobs", ["tool"], unique=False
    )
    op.create_index(
        op.f("ix_processing_jobs_status"), "processing_jobs", ["status"], unique=False
    )
    op.create_index(
        "ix_processing_jobs_expires_at",
        "processing_jobs",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "job_files",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", job_file_role, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["processing_jobs.id"],
            name=op.f("fk_job_files_job_id_processing_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["stored_files.id"],
            name=op.f("fk_job_files_file_id_stored_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "job_id", "file_id", "role", "position", name=op.f("pk_job_files")
        ),
    )


def downgrade() -> None:
    op.drop_table("job_files")
    op.drop_index("ix_processing_jobs_expires_at", table_name="processing_jobs")
    op.drop_index(op.f("ix_processing_jobs_status"), table_name="processing_jobs")
    op.drop_index(op.f("ix_processing_jobs_tool"), table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_index("ix_stored_files_expires_at", table_name="stored_files")
    op.drop_index(op.f("ix_stored_files_status"), table_name="stored_files")
    op.drop_table("stored_files")

    bind = op.get_bind()
    job_file_role.drop(bind, checkfirst=True)
    job_status.drop(bind, checkfirst=True)
    file_status.drop(bind, checkfirst=True)
    file_category.drop(bind, checkfirst=True)
