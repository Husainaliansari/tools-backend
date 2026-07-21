"""Enhance tool services: OCR, Repair, Compress Scanned PDF."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, field_validator

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService
from app.utils.ocr_language import validate_ocr_languages


class OcrOptions(BaseSchema):
    auto_detect_language: bool = Field(
        default=True,
        description="Detect the document language automatically; `language` "
        "is then only the fallback should detection come up empty.",
    )
    language: str = Field(
        default="eng",
        pattern=r"^[a-z_]{3,7}(\+[a-z_]{3,7})*$",
        description="Tesseract language code(s), e.g. 'eng' or 'eng+deu'.",
    )
    deskew: bool = Field(default=False, description="Straighten skewed scans.")
    rotate_pages: bool = Field(
        default=True,
        description="Auto-correct pages scanned sideways or upside-down.",
    )
    force_ocr: bool = Field(
        default=False,
        description="Re-OCR every page, replacing any existing text layer.",
    )

    @field_validator("language")
    @classmethod
    def _language_installed(cls, value: str) -> str:
        return validate_ocr_languages(value)


class OcrService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.OCR
    task_name: ClassVar[str] = "tools.ocr"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = OcrOptions


class RepairService(BaseToolService):
    """QPDF structural rewrite — no options."""

    slug: ClassVar[ToolSlug] = ToolSlug.REPAIR
    task_name: ClassVar[str] = "tools.repair"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = None


class CompressScannedOptions(BaseSchema):
    quality: Literal["extreme", "recommended", "less"] = Field(
        default="extreme",
        description="Scanned documents tolerate aggressive downsampling; "
        "'extreme' is usually right.",
    )


class CompressScannedService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.COMPRESS_SCANNED
    task_name: ClassVar[str] = "tools.compress-scanned"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = CompressScannedOptions
