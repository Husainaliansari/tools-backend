"""Reusable pagination dependency.

A framework-level (non-business) FastAPI dependency that parses and validates
standard pagination query parameters. Feature endpoints depend on this to get
consistent paging behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query


@dataclass(slots=True)
class PaginationParams:
    """Validated pagination parameters with SQL-friendly accessors."""

    page: int
    size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


def pagination_params(
    page: int = Query(1, ge=1, description="1-based page number."),
    size: int = Query(20, ge=1, le=100, description="Items per page (max 100)."),
) -> PaginationParams:
    """Provide validated pagination parameters to an endpoint."""
    return PaginationParams(page=page, size=size)
