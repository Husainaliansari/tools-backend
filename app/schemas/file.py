"""File API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, computed_field

from app.config import get_settings
from app.constants import FileCategory, FileStatus
from app.models.file import StoredFile
from app.schemas.base import ORMSchema
from app.utils.filenames import human_readable_size


class FileInfo(ORMSchema):
    """Public representation of a stored file."""

    id: uuid.UUID
    original_name: str
    category: FileCategory
    media_type: str
    extension: str
    size_bytes: int
    status: FileStatus
    created_at: datetime
    expires_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def size_human(self) -> str:
        return human_readable_size(self.size_bytes)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def download_url(self) -> str:
        return f"{get_settings().API_V1_PREFIX}/files/{self.id}/download"

    @classmethod
    def from_model(cls, record: StoredFile) -> FileInfo:
        return cls.model_validate(record)


class UploadResult(ORMSchema):
    """Payload returned by the multi-file upload endpoint."""

    files: list[FileInfo] = Field(default_factory=list)
    count: int = 0

    @classmethod
    def from_models(cls, records: list[StoredFile]) -> UploadResult:
        infos = [FileInfo.from_model(r) for r in records]
        return cls(files=infos, count=len(infos))
