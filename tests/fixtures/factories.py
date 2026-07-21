"""Real test-document factories (reportlab PDFs, Pillow images).

Tools 14-20 run pure-Python pipelines, so tests exercise them with genuine
documents instead of stubs.
"""

from __future__ import annotations

import io

from PIL import Image
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas


def make_pdf_bytes(pages: int = 3, text: str = "Body text") -> bytes:
    """A real multi-page PDF with extractable text on each page."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=LETTER)
    for number in range(1, pages + 1):
        canvas.setFont("Helvetica", 14)
        canvas.drawString(72, 700, f"{text} {number}")
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def make_form_pdf_bytes(field_names: tuple[str, ...] = ("name", "email")) -> bytes:
    """A real PDF with AcroForm text fields."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=LETTER)
    canvas.setFont("Helvetica", 12)
    y = 700
    for field in field_names:
        canvas.drawString(72, y + 4, f"{field}:")
        canvas.acroForm.textfield(
            name=field, x=160, y=y, width=220, height=18, borderWidth=0
        )
        y -= 40
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def make_image_only_pdf_bytes(
    *, width: int = 300, height: int = 200
) -> bytes:
    """A single-page PDF whose only content is a raster image (no text layer),
    standing in for a scanned document."""
    import fitz  # PyMuPDF — only needed by the few tests that use this factory

    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height))
    pix.set_rect(pix.irect, (30, 90, 200))
    page.insert_image(page.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def make_image_bytes(
    image_format: str = "JPEG",
    *,
    size: tuple[int, int] = (120, 90),
    color: tuple[int, ...] = (200, 30, 30),
    alpha: bool = False,
) -> bytes:
    """A real JPEG or PNG image; ``alpha=True`` adds a transparency channel."""
    mode = "RGBA" if alpha else "RGB"
    if alpha and len(color) == 3:
        color = (*color, 128)
    image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()
