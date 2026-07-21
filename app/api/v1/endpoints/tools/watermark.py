"""Watermark endpoint."""

from __future__ import annotations

from app.api.v1.endpoints.tools import create_tool_router
from app.services.tools.watermark import WatermarkService

router = create_tool_router(WatermarkService)
