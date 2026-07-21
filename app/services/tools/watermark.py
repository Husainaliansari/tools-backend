"""Add Watermark tool service.

Stamps a semi-transparent text or image watermark across PDF pages
(reportlab overlay merged via pypdf). Supports full text styling, a 3x3
position grid with offsets, tiling, above/below-content layering and
flexible page targeting.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService

PAGE_RANGE_PATTERN = r"^\d+(-\d+)?(,\d+(-\d+)?)*$"
HEX_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"

Position = Literal[
    "top-left",
    "top-center",
    "top-right",
    "center-left",
    "center",
    "center-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
]


class WatermarkOptions(BaseSchema):
    mode: Literal["text", "image"] = Field(
        default="text",
        description=(
            "'text' stamps the given text; 'image' stamps an uploaded JPG/PNG "
            "(include the image among the job's input files)."
        ),
    )

    # ── Text content & typography ────────────────────────────────────────
    text: str | None = Field(default=None, min_length=1, max_length=200)
    font_family: Literal["helvetica", "times", "courier"] = Field(
        default="helvetica"
    )
    bold: bool = Field(default=True)
    italic: bool = Field(default=False)
    underline: bool = Field(default=False)
    font_size: int = Field(default=48, ge=8, le=144)
    align: Literal["left", "center", "right"] = Field(
        default="center", description="Line alignment within multi-line text."
    )
    letter_spacing: float = Field(
        default=0.0, ge=0.0, le=20.0, description="Extra space between glyphs (pt)."
    )
    line_height: float = Field(
        default=1.2, ge=0.8, le=3.0, description="Multi-line line height multiplier."
    )
    color: str = Field(default="#808080", pattern=HEX_COLOR_PATTERN)

    # ── Shared appearance ────────────────────────────────────────────────
    opacity: float = Field(default=0.15, ge=0.05, le=1.0)
    rotation: int = Field(default=45, ge=0, le=360)

    # ── Position & layout ────────────────────────────────────────────────
    position: Position = Field(default="center")
    offset_x_mm: float = Field(
        default=0.0, ge=-200.0, le=200.0, description="Horizontal nudge (mm, + = right)."
    )
    offset_y_mm: float = Field(
        default=0.0, ge=-200.0, le=200.0, description="Vertical nudge (mm, + = down)."
    )
    margin_mm: float = Field(default=12.0, ge=0.0, le=100.0)
    tile: bool = Field(
        default=False, description="Repeat the watermark across the whole page."
    )

    # ── Image mode sizing ────────────────────────────────────────────────
    scale: float = Field(
        default=0.5,
        ge=0.05,
        le=1.0,
        description="Image mode: fraction of the page the image spans.",
    )
    keep_aspect: bool = Field(
        default=True, description="Image mode: preserve the image aspect ratio."
    )
    scale_x: float | None = Field(
        default=None,
        ge=0.05,
        le=1.0,
        description="Image mode, keep_aspect=false: width as a fraction of the page width.",
    )
    scale_y: float | None = Field(
        default=None,
        ge=0.05,
        le=1.0,
        description="Image mode, keep_aspect=false: height as a fraction of the page height.",
    )

    # ── Layering & page targeting ────────────────────────────────────────
    layer: Literal["above", "below"] = Field(
        default="above", description="Stamp over or under the page content."
    )
    pages: Literal["all", "first", "last", "odd", "even", "custom"] = Field(
        default="all"
    )
    page_range: str | None = Field(
        default=None,
        pattern=PAGE_RANGE_PATTERN,
        description="Pages to stamp when pages='custom', e.g. '1-3,7'.",
    )

    @model_validator(mode="after")
    def _validate_mode_requirements(self) -> WatermarkOptions:
        if self.mode == "text" and not (self.text and self.text.strip()):
            raise ValueError("Provide the watermark text (or switch to image mode).")
        if self.pages == "custom" and not self.page_range:
            raise ValueError("Provide a page range (or choose a different page option).")
        return self


class WatermarkService(BaseToolService):
    """Inputs are the PDFs to stamp plus, in image mode, one JPG/PNG to use
    as the watermark."""

    slug: ClassVar[ToolSlug] = ToolSlug.WATERMARK
    task_name: ClassVar[str] = "tools.watermark"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset(
        {"pdf", "jpg", "jpeg", "png"}
    )
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 11  # up to 10 PDFs + 1 watermark image
    options_model = WatermarkOptions
