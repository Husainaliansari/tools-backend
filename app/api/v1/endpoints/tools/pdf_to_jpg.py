"""PDF to JPG endpoint."""

from __future__ import annotations

from app.api.v1.endpoints.tools import create_tool_router
from app.services.tools.pdf_to_jpg import PdfToJpgService

router = create_tool_router(PdfToJpgService)
