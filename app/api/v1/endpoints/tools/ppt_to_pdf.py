"""PPT to PDF endpoint."""

from __future__ import annotations

from app.api.v1.endpoints.tools import create_tool_router
from app.services.tools.ppt_to_pdf import PptToPdfService

router = create_tool_router(PptToPdfService)
