"""Generic pagination result model.

Framework-level building block used to return paginated collections in a
consistent shape. Parameterise with a concrete item schema at the call site.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from app.schemas.base import BaseSchema

T = TypeVar("T")


class PageMeta(BaseSchema):
    """Metadata describing a page within a larger collection."""

    page: int
    size: int
    total: int
    pages: int


class Page(BaseModel, Generic[T]):
    """A single page of items plus its metadata."""

    items: list[T]
    meta: PageMeta

    @classmethod
    def create(cls, items: list[T], total: int, page: int, size: int) -> Page[T]:
        pages = (total + size - 1) // size if size else 0
        return cls(
            items=items,
            meta=PageMeta(page=page, size=size, total=total, pages=pages),
        )
