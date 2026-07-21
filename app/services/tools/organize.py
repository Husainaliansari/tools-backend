"""Organize tool services: Merge, Split, Rotate, Delete Pages, Extract Pages,
Reorder Pages. All pypdf-backed page operations."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from app.constants import ToolSlug
from app.schemas.base import BaseSchema
from app.services.tool_base import BaseToolService

PAGE_SELECTION_PATTERN = r"^\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*$"


class MergeService(BaseToolService):
    """Files merge in upload order; no options."""

    slug: ClassVar[ToolSlug] = ToolSlug.MERGE
    task_name: ClassVar[str] = "tools.merge"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 2
    max_input_files: ClassVar[int] = 20
    options_model = None


class SplitOptions(BaseSchema):
    mode: Literal["ranges", "every_page"] = "ranges"
    ranges: list[str] | None = Field(
        default=None,
        description="Page ranges, one output per entry, e.g. ['1-4', '5-8'].",
    )

    @model_validator(mode="after")
    def _ranges_required(self) -> SplitOptions:
        if self.mode == "ranges":
            if not self.ranges:
                raise ValueError("Provide at least one page range.")
            import re

            for spec in self.ranges:
                if not re.fullmatch(PAGE_SELECTION_PATTERN, spec):
                    raise ValueError(f"Invalid page range '{spec}'.")
        return self


class SplitService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.SPLIT
    task_name: ClassVar[str] = "tools.split"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 1
    options_model = SplitOptions


class RotateOptions(BaseSchema):
    angle: Literal[90, 180, 270] = 90
    pages: str | None = Field(
        default=None,
        pattern=PAGE_SELECTION_PATTERN,
        description="Pages to rotate, e.g. '1,3-5'. All pages when omitted.",
    )
    apply_to: Literal["all", "odd", "even"] = "all"


class RotateService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.ROTATE
    task_name: ClassVar[str] = "tools.rotate"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = RotateOptions


class PageSelectionOptions(BaseSchema):
    pages: str = Field(
        ...,
        pattern=PAGE_SELECTION_PATTERN,
        description="Page selection, e.g. '2,5-7'.",
    )


class DeletePagesService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.DELETE_PAGES
    task_name: ClassVar[str] = "tools.delete-pages"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 1
    options_model = PageSelectionOptions


class ExtractPagesService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.EXTRACT_PAGES
    task_name: ClassVar[str] = "tools.extract-pages"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 1
    options_model = PageSelectionOptions


class ReorderOptions(BaseSchema):
    order: list[int] = Field(
        ...,
        min_length=1,
        description="New page order as a permutation of 1..N, e.g. [3,1,2].",
    )


class ReorderService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.REORDER_PAGES
    task_name: ClassVar[str] = "tools.reorder"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 1
    options_model = ReorderOptions
