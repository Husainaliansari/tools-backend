"""Reusable, framework-level field validators.

These are generic helpers intended to be attached to feature schemas via
``Annotated`` types or ``field_validator``. They contain no business rules.
"""

from __future__ import annotations


def strip_to_none(value: str | None) -> str | None:
    """Trim a string and coerce empty results to ``None``."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_lower(value: str | None) -> str | None:
    """Lower-case and trim a string (e.g. for case-insensitive identifiers)."""
    if value is None:
        return None
    return value.strip().lower()


def ensure_non_empty(value: str) -> str:
    """Raise ``ValueError`` if a string is empty after stripping."""
    if not value or not value.strip():
        raise ValueError("Value must not be empty.")
    return value.strip()
