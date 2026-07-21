"""PDF to PNG tool service.

Same pipeline as PDF→JPG (shared options schema and worker processor); PNG is
the right choice for lossless page captures and diagrams.
"""

from __future__ import annotations

from typing import ClassVar

from app.constants import ToolSlug
from app.services.tool_base import BaseToolService
from app.services.tools.pdf_to_jpg import PdfToImageOptions


class PdfToPngService(BaseToolService):
    slug: ClassVar[ToolSlug] = ToolSlug.PDF_TO_PNG
    task_name: ClassVar[str] = "tools.pdf-to-png"
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 10
    options_model = PdfToImageOptions
