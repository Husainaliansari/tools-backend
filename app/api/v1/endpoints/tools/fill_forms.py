"""FillForms endpoint."""

from __future__ import annotations

from app.api.v1.endpoints.tools import create_tool_router
from app.services.tools.document import FillFormsService

router = create_tool_router(FillFormsService)
