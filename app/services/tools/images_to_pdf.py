"""JPG→PDF and PNG→PDF tool services.

Both combine several uploaded images into a single PDF (in upload order) via
img2pdf. They differ only in accepted input types.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService


class ImagesToPdfOptions(BaseSchema):
    page_size: Literal["fit", "a4", "letter"] = Field(
        default="fit",
        description="'fit' sizes each page to its image; a4/letter centre it.",
    )
    orientation: Literal["portrait", "landscape"] = Field(
        default="portrait",
        description="Page orientation for fixed page sizes (ignored for 'fit').",
    )
    margin_mm: float = Field(
        default=10.0,
        ge=0,
        le=50,
        description="Page margin in millimetres (fixed page sizes only).",
    )


class JpgToPdfService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.JPG_TO_PDF
    task_name: ClassVar[str] = "tools.jpg-to-pdf"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"jpg", "jpeg"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 20
    options_model = ImagesToPdfOptions


class PngToPdfService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.PNG_TO_PDF
    task_name: ClassVar[str] = "tools.png-to-pdf"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"png"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 20
    options_model = ImagesToPdfOptions
