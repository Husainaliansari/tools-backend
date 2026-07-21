"""Standardised API response envelopes.

A single, predictable response shape across every endpoint dramatically
simplifies client code and error handling. These generics are framework-level
building blocks — concrete endpoints parameterise them with their own data
schemas (added later, per feature).
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.schemas.base import BaseSchema

T = TypeVar("T")


class ErrorDetail(BaseSchema):
    """A single, granular error (e.g. one invalid field)."""

    message: str = Field(..., description="Human-readable error description.")
    field: str | None = Field(
        default=None, description="Input field the error relates to, if any."
    )
    type: str | None = Field(
        default=None, description="Machine-readable error type/category."
    )


class ErrorInfo(BaseSchema):
    """Structured error information returned to clients."""

    code: str = Field(..., description="Stable, machine-readable error code.")
    message: str = Field(..., description="Human-readable summary of the error.")
    details: list[ErrorDetail] = Field(default_factory=list)


class SuccessResponse(BaseModel, Generic[T]):
    """Envelope for successful responses."""

    success: bool = True
    data: T | None = None
    message: str | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Envelope for error responses. Mirrors :class:`SuccessResponse`."""

    success: bool = False
    error: ErrorInfo
    request_id: str | None = None
