"""Tool task modules — one Celery task per PDF tool, named ``tools.<slug>``.

Imported by ``app.tasks`` so the tasks register when the worker (or an eager
test run) loads the package.
"""

from __future__ import annotations

from app.tasks.tools import (
    compress,
    convert_office,
    document,
    enhance,
    images_to_pdf,
    organize,
    pdf_security,
    pdf_to_images,
    ppt_to_pdf,
    stamp,
)

__all__ = [
    "compress",
    "convert_office",
    "document",
    "enhance",
    "images_to_pdf",
    "organize",
    "pdf_security",
    "pdf_to_images",
    "ppt_to_pdf",
    "stamp",
]
