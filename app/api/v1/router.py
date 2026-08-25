"""Version 1 API router aggregator.

Collects every ``v1`` feature router into a single router that the top-level
API router mounts under the versioned prefix. Tool routers are included here
as each tool is implemented.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import analytics, feedback, files, jobs
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.tools import (
    compare,
    compress,
    compress_scanned,
    delete_pages,
    excel_to_pdf,
    extract_pages,
    fill_forms,
    header_footer,
    jpg_to_pdf,
    merge,
    metadata,
    ocr,
    page_numbers,
    pdf_to_jpg,
    pdf_to_png,
    pdf_to_word,
    png_to_pdf,
    ppt_to_pdf,
    protect,
    redact,
    remove_watermark,
    reorder,
    repair,
    rotate,
    sign,
    split,
    unlock,
    watermark,
    word_to_pdf,
)

api_v1_router = APIRouter()
api_v1_router.include_router(analytics.router)
api_v1_router.include_router(files.router)
api_v1_router.include_router(jobs.router)
api_v1_router.include_router(feedback.router)
api_v1_router.include_router(admin_router)

# Tool endpoints (one per implemented tool).
for _tool_module in (
    compress,
    merge,
    split,
    rotate,
    delete_pages,
    extract_pages,
    reorder,
    pdf_to_word,
    word_to_pdf,
    excel_to_pdf,
    ppt_to_pdf,
    pdf_to_jpg,
    pdf_to_png,
    jpg_to_pdf,
    png_to_pdf,
    watermark,
    remove_watermark,
    header_footer,
    page_numbers,
    protect,
    unlock,
    ocr,
    repair,
    compress_scanned,
    metadata,
    compare,
    redact,
    fill_forms,
    sign,
):
    api_v1_router.include_router(_tool_module.router)
