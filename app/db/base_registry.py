"""Model registry for Alembic autogeneration.

Alembic must import every model module so that the tables are registered on
``Base.metadata`` before it diffs the schema. This module is the single import
target for that purpose — as feature models are added under ``app/models/``,
import them here, e.g.::

    from app.models.user import User  # noqa: F401

"""

from __future__ import annotations

from app.db.base import Base
from app.models.file import StoredFile
from app.models.job import JobFile, ProcessingJob
from app.models.user import User

__all__ = ["Base", "JobFile", "ProcessingJob", "StoredFile", "User"]
