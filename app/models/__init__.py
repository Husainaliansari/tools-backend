"""Models package (persistence layer).

SQLAlchemy ORM models live here, one module per aggregate/entity, each
inheriting from :class:`app.db.base.Base`. Remember to import new model modules
in ``app/db/base_registry.py`` so Alembic can autogenerate migrations for them.
"""

from __future__ import annotations

from app.models.file import StoredFile
from app.models.job import JobFile, ProcessingJob

__all__ = ["JobFile", "ProcessingJob", "StoredFile"]
