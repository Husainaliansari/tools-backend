"""User account model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A registered account. Files and jobs may belong to a user; anonymous
    usage remains possible (rows with ``user_id IS NULL``)."""

    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(
        String(254), nullable=False, unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.id} {self.email!r}>"
