"""Compare endpoint."""

from __future__ import annotations

from app.api.v1.endpoints.tools import create_tool_router
from app.services.tools.document import CompareService

router = create_tool_router(CompareService)
