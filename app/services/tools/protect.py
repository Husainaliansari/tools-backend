"""Protect PDF tool service.

Encrypts PDFs with AES-256 (pypdf + cryptography) and applies user-access
permission flags. Passwords are redacted from the persisted job options once
the job reaches a terminal state.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService


class ProtectOptions(BaseSchema):
    user_password: str = Field(
        ...,
        min_length=4,
        max_length=128,
        description="Password required to open the document.",
    )
    owner_password: str | None = Field(
        default=None,
        min_length=4,
        max_length=128,
        description="Password that bypasses restrictions (defaults to the "
        "user password).",
    )
    allow_printing: bool = True
    allow_copying: bool = False
    allow_modification: bool = False


class ProtectService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.PROTECT
    task_name: ClassVar[str] = "tools.protect"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = ProtectOptions
