"""Tool services — one module per PDF tool, all built on
:class:`app.services.tool_base.BaseToolService`."""

from __future__ import annotations

from app.services.tools.compress import CompressService
from app.services.tools.convert_office import (
    ExcelToPdfService,
    PdfToWordService,
    WordToPdfService,
)
from app.services.tools.document import (
    CompareService,
    FillFormsService,
    MetadataService,
    RedactService,
    SignService,
)
from app.services.tools.enhance import (
    CompressScannedService,
    OcrService,
    RepairService,
)
from app.services.tools.header_footer import HeaderFooterService
from app.services.tools.images_to_pdf import JpgToPdfService, PngToPdfService
from app.services.tools.organize import (
    DeletePagesService,
    ExtractPagesService,
    MergeService,
    ReorderService,
    RotateService,
    SplitService,
)
from app.services.tools.page_numbers import PageNumbersService
from app.services.tools.pdf_to_jpg import PdfToJpgService
from app.services.tools.pdf_to_png import PdfToPngService
from app.services.tools.ppt_to_pdf import PptToPdfService
from app.services.tools.protect import ProtectService
from app.services.tools.remove_watermark import RemoveWatermarkService
from app.services.tools.unlock import UnlockService
from app.services.tools.watermark import WatermarkService

__all__ = [
    "CompareService",
    "CompressScannedService",
    "CompressService",
    "DeletePagesService",
    "ExcelToPdfService",
    "ExtractPagesService",
    "FillFormsService",
    "HeaderFooterService",
    "JpgToPdfService",
    "MergeService",
    "MetadataService",
    "OcrService",
    "PageNumbersService",
    "PdfToJpgService",
    "PdfToPngService",
    "PdfToWordService",
    "PngToPdfService",
    "PptToPdfService",
    "ProtectService",
    "RedactService",
    "RemoveWatermarkService",
    "ReorderService",
    "RepairService",
    "RotateService",
    "SignService",
    "SplitService",
    "UnlockService",
    "WatermarkService",
    "WordToPdfService",
]
