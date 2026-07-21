"""PPT to PDF tool service.

Converts PowerPoint presentations (``.ppt``/``.pptx``) to PDF via LibreOffice.
Accepts several presentations in one job and produces one PDF per input.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService

# "1-3", "5", "1-3,7,10-12" — LibreOffice PageRange syntax.
_RANGE_PATTERN = r"^\d+(-\d+)?(,\d+(-\d+)?)*$"


class PptToPdfOptions(BaseSchema):
    pdf_a: bool = Field(
        default=False,
        description="Export as archival PDF/A-2b instead of regular PDF.",
    )
    slide_range: str | None = Field(
        default=None,
        pattern=_RANGE_PATTERN,
        description="Slides to export, e.g. '1-3,7'. All slides when omitted.",
    )


class PptToPdfService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.PPT_TO_PDF
    task_name: ClassVar[str] = "tools.ppt-to-pdf"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"ppt", "pptx"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = PptToPdfOptions
