"""Remove Watermark tool service.

Automatically detects and removes watermark annotations, ``/Artifact``
watermark stamps, optional-content layers, and flattened text/image
watermarks (recognised by rotation, transparency, tiling and cross-page
repetition). Watermarks baked into a scanned page's raster image cannot be
separated. The optional ``text`` is a manual override for text watermarks
the automatic detection misses.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService


class RemoveWatermarkOptions(BaseSchema):
    mode: Literal["annotations", "layers", "both"] = Field(
        default="both",
        description=(
            "What to remove: watermark annotations, watermark OCG layers, " "or both."
        ),
    )
    text: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description=(
            "Optional override: also remove every text block containing "
            "this text — for watermarks the automatic detection misses."
        ),
    )


class RemoveWatermarkService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.REMOVE_WATERMARK
    task_name: ClassVar[str] = "tools.remove-watermark"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = RemoveWatermarkOptions
