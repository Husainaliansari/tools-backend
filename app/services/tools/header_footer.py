"""Header & Footer tool service.

Stamps header/footer lines onto the selected pages. Templates support the
placeholders ``{page}``, ``{total}``, ``{date}``, ``{time}`` and
``{filename}``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService
from app.services.tools.watermark import HEX_COLOR_PATTERN, PAGE_RANGE_PATTERN

HFAlign = Literal["left", "center", "right"]


class HeaderFooterOptions(BaseSchema):
    header_text: str | None = Field(default=None, max_length=200)
    footer_text: str | None = Field(default=None, max_length=200)

    # ── Typography & appearance ──────────────────────────────────────────
    font_family: Literal["helvetica", "times", "courier"] = "helvetica"
    font_size: int = Field(default=10, ge=6, le=36)
    bold: bool = Field(default=False)
    italic: bool = Field(default=False)
    color: str = Field(default="#333333", pattern=HEX_COLOR_PATTERN)
    opacity: float = Field(default=1.0, ge=0.1, le=1.0)
    margin_mm: float = Field(default=12.0, ge=5, le=40)

    # ── Position ─────────────────────────────────────────────────────────
    align: HFAlign = Field(
        default="center", description="Shared default alignment for both lines."
    )
    header_align: HFAlign | None = Field(
        default=None, description="Overrides align for the header."
    )
    footer_align: HFAlign | None = Field(
        default=None, description="Overrides align for the footer."
    )

    # ── Page targeting ───────────────────────────────────────────────────
    pages: Literal["all", "first", "last", "odd", "even", "custom"] = Field(
        default="all"
    )
    page_range: str | None = Field(
        default=None,
        pattern=PAGE_RANGE_PATTERN,
        description="Pages to stamp when pages='custom', e.g. '1-3,7'.",
    )

    @model_validator(mode="after")
    def _validate(self) -> HeaderFooterOptions:
        if not self.header_text and not self.footer_text:
            raise ValueError("Provide header_text, footer_text or both.")
        if self.pages == "custom" and not self.page_range:
            raise ValueError(
                "Provide a page range (or choose a different page option)."
            )
        return self


class HeaderFooterService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.HEADER_FOOTER
    task_name: ClassVar[str] = "tools.header-footer"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = HeaderFooterOptions
