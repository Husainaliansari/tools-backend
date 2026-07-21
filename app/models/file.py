"""Stored file model.

One row per physical file on disk — uploads, processed outputs and thumbnails
alike. The row records where the file lives (category + relative path inside
the storage tree), what it is (media type, size, checksum) and when the
cleanup scheduler may remove it (``expires_at``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import FileCategory, FileStatus
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.job import JobFile


class StoredFile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A file persisted in the local storage tree."""

    __tablename__ = "stored_files"

    # Original client-supplied name, kept only for display / download naming.
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Name on disk (UUID-based, collision-free, never client-controlled).
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Which branch of the storage tree the file lives in.
    category: Mapped[FileCategory] = mapped_column(
        Enum(
            FileCategory,
            name="file_category",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=FileCategory.UPLOAD,
    )
    # Path relative to that branch's root (e.g. "2026/07/07/<uuid>.pdf").
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)

    media_type: Mapped[str] = mapped_column(String(127), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[FileStatus] = mapped_column(
        Enum(
            FileStatus,
            name="file_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=FileStatus.ACTIVE,
        index=True,
    )
    # Owner; NULL = anonymous upload (accessible without authentication).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    job_links: Mapped[list[JobFile]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    __table_args__ = (Index("ix_stored_files_expires_at", "expires_at"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<StoredFile {self.id} {self.original_name!r} {self.status}>"
