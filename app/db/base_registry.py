"""Model registry for Alembic autogeneration.

Alembic must import every model module so that the tables are registered on
``Base.metadata`` before it diffs the schema. This module is the single import
target for that purpose — as feature models are added under ``app/models/``,
import them here, e.g.::

    from app.models.user import User  # noqa: F401

"""

from __future__ import annotations

from app.db.base import Base
from app.models.admin import (
    AdminAuditLog,
    Announcement,
    AppSetting,
    BlogPost,
    ContactMessage,
    ContentPage,
    ErrorLog,
    Faq,
    Subscription,
    ToolConfig,
)
from app.models.feedback import Feedback
from app.models.file import StoredFile
from app.models.job import JobFile, ProcessingJob
from app.models.user import User

__all__ = [
    "AdminAuditLog",
    "Announcement",
    "AppSetting",
    "Base",
    "BlogPost",
    "ContactMessage",
    "ContentPage",
    "ErrorLog",
    "Faq",
    "Feedback",
    "JobFile",
    "ProcessingJob",
    "StoredFile",
    "Subscription",
    "ToolConfig",
    "User",
]
