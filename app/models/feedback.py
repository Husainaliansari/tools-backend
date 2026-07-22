"""Visitor feedback model.

One row per submission of the public *Feedback & Suggestions* form. Stores the
message and, optionally, a single screenshot attachment inline (images are
capped at ~1 MB, so a ``BYTEA`` column keeps everything in one table without
filesystem plumbing or a cleanup schedule). ``client_ip`` and ``user_id``
support the once-per-day anti-spam limit and let us attribute feedback to a
signed-in account when there is one.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, Index, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import FeedbackCategory
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Feedback(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single feedback / bug report / suggestion submission."""

    __tablename__ = "feedback"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[FeedbackCategory] = mapped_column(
        Enum(
            FeedbackCategory,
            name="feedback_category",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=FeedbackCategory.GENERAL,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional inline screenshot (images only, size-capped at the API layer).
    attachment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_content_type: Mapped[str | None] = mapped_column(
        String(127), nullable=True
    )
    attachment_size: Mapped[int | None] = mapped_column(nullable=True)
    attachment_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Anti-spam / attribution.
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (Index("ix_feedback_created_at", "created_at"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Feedback {self.id} {self.email!r} {self.category}>"
