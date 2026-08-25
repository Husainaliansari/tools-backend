"""Analytics schema for request validation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PageVisitCreate(BaseModel):
    visitor_id: str = Field(..., min_length=1, max_length=64)
    session_id: str = Field(..., min_length=1, max_length=64)
    path: str = Field(..., min_length=1, max_length=512)
    referrer: str | None = Field(default=None, max_length=512)
    source: str | None = Field(default=None, max_length=64)
