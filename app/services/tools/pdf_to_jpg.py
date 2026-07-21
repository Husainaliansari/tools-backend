"""PDF to JPG tool service.

Renders every page of the input PDFs to JPG images via Poppler's ``pdftoppm``.
Produces one image per page; multi-page results are conveniently fetched as a
single archive through ``GET /jobs/{id}/download``.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field, model_validator

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService


class PdfToImageOptions(BaseSchema):
    """Rendering options shared by the PDF→JPG and PDF→PNG tools."""

    dpi: int = Field(
        default=150,
        ge=36,
        le=600,
        description="Render resolution. 150 suits screens; 300+ for print.",
    )
    quality: int = Field(
        default=90,
        ge=1,
        le=100,
        description="JPEG quality (ignored for PNG).",
    )
    grayscale: bool = Field(default=False, description="Render pages in grayscale.")
    first_page: int | None = Field(
        default=None, ge=1, description="First page to render (1-based)."
    )
    last_page: int | None = Field(
        default=None, ge=1, description="Last page to render (inclusive)."
    )

    @model_validator(mode="after")
    def _check_range(self) -> PdfToImageOptions:
        if (
            self.first_page is not None
            and self.last_page is not None
            and self.last_page < self.first_page
        ):
            raise ValueError("last_page must not be smaller than first_page.")
        return self


class PdfToJpgService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.PDF_TO_JPG
    task_name: ClassVar[str] = "tools.pdf-to-jpg"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = PdfToImageOptions
