"""Office conversion tool services: Word→PDF, Excel→PDF (LibreOffice) and
PDF→Word (pdf2docx)."""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field, model_validator

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService


class OfficeToPdfOptions(BaseSchema):
    pdf_a: bool = Field(
        default=False,
        description="Export as archival PDF/A-2b instead of regular PDF.",
    )


class WordToPdfService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.WORD_TO_PDF
    task_name: ClassVar[str] = "tools.word-to-pdf"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"doc", "docx"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = OfficeToPdfOptions


class ExcelToPdfService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.EXCEL_TO_PDF
    task_name: ClassVar[str] = "tools.excel-to-pdf"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"xls", "xlsx"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = OfficeToPdfOptions


class PdfToWordOptions(BaseSchema):
    first_page: int | None = Field(default=None, ge=1)
    last_page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check_range(self) -> PdfToWordOptions:
        if (
            self.first_page is not None
            and self.last_page is not None
            and self.last_page < self.first_page
        ):
            raise ValueError("last_page must not be smaller than first_page.")
        return self


class PdfToWordService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.PDF_TO_WORD
    task_name: ClassVar[str] = "tools.pdf-to-word"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = PdfToWordOptions
