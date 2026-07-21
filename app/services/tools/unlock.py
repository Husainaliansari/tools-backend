"""Unlock PDF tool service — removes encryption given the correct password.

The natural counterpart to Protect. The password is redacted from the
persisted job options after processing (same mechanism as Protect).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService


class UnlockOptions(BaseSchema):
    password: str = Field(..., min_length=1, max_length=128)


class UnlockService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.UNLOCK
    task_name: ClassVar[str] = "tools.unlock"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = UnlockOptions
