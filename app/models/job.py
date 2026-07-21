"""Processing job models.

A :class:`ProcessingJob` is one execution of a PDF tool. Its input and output
files are linked through the :class:`JobFile` association table (``position``
preserves input ordering, which matters for tools like Merge).

The worker updates ``status``/``progress`` as it runs; the Processing Status
API reads the same row, so clients can poll a single endpoint for any tool.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import JobFileRole, JobStatus
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.file import StoredFile


class ProcessingJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One background execution of a PDF tool."""

    __tablename__ = "processing_jobs"

    tool: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="job_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=JobStatus.PENDING,
        index=True,
    )
    # 0-100; workers update this as they progress through the pipeline.
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # Tool-specific options, validated by the tool's schema before enqueueing.
    options: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    celery_task_id: Mapped[str | None] = mapped_column(String(155), nullable=True)

    # Owner; NULL = anonymous job.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    files: Mapped[list[JobFile]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobFile.position",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_processing_jobs_expires_at", "expires_at"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProcessingJob {self.id} {self.tool} {self.status}>"


class JobFile(Base):
    """Association between a job and one of its input/output files."""

    __tablename__ = "job_files"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stored_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[JobFileRole] = mapped_column(
        Enum(
            JobFileRole,
            name="job_file_role",
            values_callable=lambda e: [m.value for m in e],
        ),
        primary_key=True,
    )
    # Ordering of inputs (e.g. merge order) and outputs (e.g. split parts).
    # Part of the PK so the same file can appear at several positions
    # (e.g. merging a document with itself).
    position: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)

    job: Mapped[ProcessingJob] = relationship(back_populates="files")
    file: Mapped[StoredFile] = relationship(back_populates="job_links", lazy="joined")
