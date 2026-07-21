"""ExtractPages endpoint."""

from __future__ import annotations

from app.api.v1.endpoints.tools import create_tool_router
from app.services.tools.organize import ExtractPagesService

router = create_tool_router(ExtractPagesService)
