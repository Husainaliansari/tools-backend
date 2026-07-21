"""PDF Compressor tool service (Ghostscript pdfwrite presets)."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService


class CompressOptions(BaseSchema):
    quality: Literal["extreme", "recommended", "less"] = Field(
        default="recommended",
        description=(
            "extreme = smallest file (72 dpi images), recommended = good "
            "screen quality (150 dpi), less = light compression (300 dpi)."
        ),
    )


class CompressService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.COMPRESS
    task_name: ClassVar[str] = "tools.compress"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = CompressOptions
