"""Common package.

Shared, cross-cutting building blocks that are generic enough to be used by any
feature but are not pure utilities (e.g. pagination result models). Distinct
from ``utils`` (stateless helpers) and ``schemas`` (request/response contracts).
"""

from app.common.pagination import Page, PageMeta

__all__ = ["Page", "PageMeta"]
