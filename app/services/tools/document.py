"""Document tool services: Metadata, Compare, Redact, Fill Forms, Sign."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService


class MetadataOptions(BaseSchema):
    title: str | None = Field(default=None, max_length=255)
    author: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=255)
    keywords: str | None = Field(default=None, max_length=255)
    clear_existing: bool = Field(
        default=False, description="Drop all existing metadata first."
    )

    @model_validator(mode="after")
    def _something_to_do(self) -> MetadataOptions:
        if not self.clear_existing and not any(
            (self.title, self.author, self.subject, self.keywords)
        ):
            raise ValueError("Provide at least one metadata field to set.")
        return self


class MetadataService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.METADATA
    task_name: ClassVar[str] = "tools.metadata"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = MetadataOptions


class CompareService(BaseToolService):
    """Exactly two PDFs, compared in upload order (A then B)."""

    slug: ClassVar[ToolSlug] = ToolSlug.COMPARE
    task_name: ClassVar[str] = "tools.compare"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 2
    max_input_files: ClassVar[int] = 2
    options_model = None


RedactAreaMode = Literal["black", "white", "color", "blur", "pixelate"]


class RedactArea(BaseSchema):
    """A rectangle to redact, in PDF points with a top-left origin.

    Whatever the visual style, the content underneath is permanently removed
    from the document; the style only controls what is painted in its place —
    a solid fill (``black``/``white``/``color``) or an irreversible raster of
    the original look (``blur``/``pixelate``).
    """

    page: int = Field(..., ge=1, description="1-based page number.")
    x0: float = Field(..., ge=0)
    y0: float = Field(..., ge=0)
    x1: float = Field(..., ge=0)
    y1: float = Field(..., ge=0)
    mode: RedactAreaMode = Field(
        default="black", description="Cover style painted after content removal."
    )
    color: str = Field(
        default="#000000",
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Fill color for the 'color' mode.",
    )
    opacity: float = Field(
        default=1.0,
        ge=0.05,
        le=1.0,
        description="Fill opacity for the 'color' mode (content is removed "
        "regardless; this only tints the empty area).",
    )

    @model_validator(mode="after")
    def _positive_size(self) -> RedactArea:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("Area must have x1 > x0 and y1 > y0.")
        return self


class RedactOptions(BaseSchema):
    texts: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="Strings to find and permanently remove.",
    )
    areas: list[RedactArea] = Field(
        default_factory=list,
        max_length=200,
        description="Page rectangles to permanently remove (for scanned pages, "
        "images, or regions with no searchable text).",
    )

    @model_validator(mode="after")
    def _something_to_redact(self) -> RedactOptions:
        self.texts = [t.strip() for t in self.texts if t.strip()]
        if not self.texts and not self.areas:
            raise ValueError("Provide at least one text term or area to redact.")
        return self


class RedactService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.REDACT
    task_name: ClassVar[str] = "tools.redact"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = RedactOptions


class FillFormsOptions(BaseSchema):
    fields: dict[str, str] = Field(
        ..., min_length=1, description="AcroForm field name → value."
    )


class FillFormsService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.FILL_FORMS
    task_name: ClassVar[str] = "tools.fill-forms"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 1
    options_model = FillFormsOptions


SignPosition = Literal[
    "bottom-right", "bottom-left", "bottom-center", "top-right", "top-left"
]


class SignOptions(BaseSchema):
    """Visual signature stamp (not a cryptographic digital signature)."""

    page: int | None = Field(
        default=None, ge=1, description="Page to sign (default: last page)."
    )
    position: SignPosition = "bottom-right"
    scale: float = Field(
        default=0.25,
        ge=0.05,
        le=0.8,
        description="Signature width as a fraction of the page width.",
    )
    margin_mm: float = Field(default=15.0, ge=0, le=60)


class SignService(BaseToolService):
    """Inputs: the PDF(s) to sign plus one JPG/PNG signature image."""

    slug: ClassVar[ToolSlug] = ToolSlug.SIGN
    task_name: ClassVar[str] = "tools.sign"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset(
        {"pdf", "jpg", "jpeg", "png"}
    )
    min_input_files: ClassVar[int] = 2  # at least one PDF + the signature image
    max_input_files: ClassVar[int] = 11
    options_model = SignOptions
