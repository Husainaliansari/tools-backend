"""Page Numbers tool service.

Stamps page numbers at a chosen position. The format template must reference
``{page}`` and may use ``{total}`` (both shifted by ``start_at``).
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, field_validator

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService
from app.services.tools.watermark import HEX_COLOR_PATTERN

Position = Literal[
    "bottom-center",
    "bottom-left",
    "bottom-right",
    "top-center",
    "top-left",
    "top-right",
]


class PageNumbersOptions(BaseSchema):
    format: str = Field(
        default="{page}",
        max_length=100,
        description="Template, e.g. 'Page {page} of {total}'.",
    )
    position: Position = "bottom-center"
    start_at: int = Field(
        default=1, ge=1, description="Number shown on the first stamped page."
    )
    skip_first: bool = Field(
        default=False, description="Leave the first page unnumbered (cover)."
    )
    font_size: int = Field(default=10, ge=6, le=36)
    color: str = Field(default="#333333", pattern=HEX_COLOR_PATTERN)
    margin_mm: float = Field(default=12.0, ge=5, le=40)

    @field_validator("format")
    @classmethod
    def _must_reference_page(cls, value: str) -> str:
        if "{page}" not in value:
            raise ValueError("format must contain the {page} placeholder.")
        return value


class PageNumbersService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.PAGE_NUMBERS
    task_name: ClassVar[str] = "tools.page-numbers"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = PageNumbersOptions
