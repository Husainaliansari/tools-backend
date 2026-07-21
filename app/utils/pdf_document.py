"""Document-level PDF operations: metadata editing, text comparison,
text redaction (PyMuPDF) and form filling (pypdf)."""

from __future__ import annotations

import difflib
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import NameObject
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

from app.exceptions.jobs import ProcessingError
from app.logging import get_logger
from app.utils.pdf_pages import open_pdf

logger = get_logger(__name__)

_META_KEYS = {
    "title": "/Title",
    "author": "/Author",
    "subject": "/Subject",
    "keywords": "/Keywords",
}


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #
def set_metadata(
    source: Path,
    destination: Path,
    *,
    fields: dict[str, str],
    clear_existing: bool = False,
) -> Path:
    """Write document info fields (title/author/subject/keywords)."""
    reader = open_pdf(source)
    writer = PdfWriter()
    writer.append(reader)

    if not clear_existing and reader.metadata:
        writer.add_metadata(dict(reader.metadata))
    writer.add_metadata(
        {_META_KEYS[key]: value for key, value in fields.items() if key in _META_KEYS}
    )
    with destination.open("wb") as handle:
        writer.write(handle)
    return destination


# --------------------------------------------------------------------------- #
# Compare (text-level)
# --------------------------------------------------------------------------- #
def compare_pdfs(first: Path, second: Path, report_path: Path) -> dict:
    """Text-level comparison; writes a human-readable report PDF.

    Compares extracted text page by page (scanned documents without a text
    layer will register as identical — run OCR first). Returns a summary dict.
    """
    reader_a, reader_b = open_pdf(first), open_pdf(second)
    pages_a = [page.extract_text() or "" for page in reader_a.pages]
    pages_b = [page.extract_text() or "" for page in reader_b.pages]
    total = max(len(pages_a), len(pages_b))

    changed_pages: list[tuple[int, float, list[str]]] = []
    for index in range(total):
        text_a = pages_a[index] if index < len(pages_a) else ""
        text_b = pages_b[index] if index < len(pages_b) else ""
        ratio = difflib.SequenceMatcher(None, text_a, text_b).ratio()
        if ratio < 0.999:
            diff = [
                line
                for line in difflib.unified_diff(
                    text_a.splitlines(), text_b.splitlines(), lineterm="", n=0
                )
                if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
            ]
            changed_pages.append((index + 1, ratio, diff[:20]))

    canvas = Canvas(str(report_path), pagesize=LETTER)
    _width, height = LETTER
    y = height - 72
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(72, y, "PDF Comparison Report")
    y -= 28
    canvas.setFont("Helvetica", 11)
    canvas.drawString(72, y, f"Document A: {first.name} ({len(pages_a)} pages)")
    y -= 16
    canvas.drawString(72, y, f"Document B: {second.name} ({len(pages_b)} pages)")
    y -= 16
    canvas.drawString(
        72,
        y,
        f"Changed pages: {len(changed_pages)} of {total}"
        + ("" if changed_pages else " — documents are textually identical"),
    )
    y -= 26

    for page_number, ratio, diff in changed_pages:
        if y < 100:
            canvas.showPage()
            y = height - 72
            canvas.setFont("Helvetica", 11)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(72, y, f"Page {page_number} — {ratio * 100:.0f}% similar")
        y -= 16
        canvas.setFont("Helvetica", 9)
        for line in diff:
            if y < 80:
                canvas.showPage()
                y = height - 72
                canvas.setFont("Helvetica", 9)
            canvas.drawString(84, y, line[:110])
            y -= 12
        y -= 8

    canvas.save()
    return {"changed_pages": len(changed_pages), "total_pages": total}


# --------------------------------------------------------------------------- #
# Redact (true content removal via PyMuPDF)
# --------------------------------------------------------------------------- #
def _redaction_flags(fitz) -> dict:
    """apply_redactions kwargs that preserve surrounding layout.

    Text under a redaction box is removed and image *pixels* under the box are
    blanked (both genuine, irreversible removal), but vector line-art is left
    intact — otherwise a single redacted word sitting on a table rule would
    delete the whole rule across the page. The opaque black box still covers
    whatever remains beneath it. The flag is looked up defensively because
    older PyMuPDF builds omit it.
    """
    kwargs: dict = {}
    line_art_none = getattr(fitz, "PDF_REDACT_LINE_ART_NONE", None)
    if line_art_none is not None:
        kwargs["graphics"] = line_art_none
    return kwargs


_AREA_MODES = frozenset({"black", "white", "color", "blur", "pixelate"})


def _hex_to_rgb01(value: str) -> tuple[float, float, float]:
    """``#rrggbb`` → PyMuPDF's (r, g, b) floats in 0–1; black on bad input."""
    raw = (value or "").lstrip("#")
    if len(raw) != 6:
        return (0.0, 0.0, 0.0)
    try:
        return tuple(int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0.0, 0.0, 0.0)


def _areas_by_page(areas: list[dict], page_count: int) -> dict[int, list[dict]]:
    """Validate area specs and group them by 0-based page index.

    Each area is ``{"page": 1-based, "x0", "y0", "x1", "y1"}`` in PDF points
    with a top-left origin, plus optional styling: ``mode`` (black | white |
    color | blur | pixelate, default black), ``color`` (#rrggbb, for the
    color mode) and ``opacity`` (0–1 fill opacity, color mode only). Raises
    :class:`ProcessingError` with a specific message for out-of-range pages
    or degenerate rectangles.
    """
    grouped: dict[int, list[dict]] = {}
    for position, area in enumerate(areas, start=1):
        try:
            page = int(area["page"])
            rect = (
                float(area["x0"]),
                float(area["y0"]),
                float(area["x1"]),
                float(area["y1"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProcessingError(
                f"Redaction area #{position} is malformed "
                "(needs page, x0, y0, x1, y1)."
            ) from exc
        if not 1 <= page <= page_count:
            raise ProcessingError(
                f"Redaction area #{position} points to page {page}, but this "
                f"document has {page_count} page(s)."
            )
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            raise ProcessingError(
                f"Redaction area #{position} has zero or negative size "
                "(x1 must be greater than x0, and y1 greater than y0)."
            )
        mode = str(area.get("mode") or "black").lower()
        if mode not in _AREA_MODES:
            raise ProcessingError(
                f"Redaction area #{position} has unknown mode '{mode}'."
            )
        try:
            opacity = min(1.0, max(0.05, float(area.get("opacity", 1.0))))
        except (TypeError, ValueError):
            opacity = 1.0
        grouped.setdefault(page - 1, []).append(
            {
                "rect": rect,
                "mode": mode,
                "color": _hex_to_rgb01(str(area.get("color") or "#000000")),
                "opacity": opacity,
            }
        )
    return grouped


def _obscured_region_png(fitz, page, rect, mode: str) -> bytes:
    """Render ``rect`` of ``page`` and return blurred/pixelated PNG bytes.

    Called *before* the page's redactions are applied, so the raster shows
    the original look — but only this unreadable raster survives in the
    output; the underlying text/vectors/image data are removed.
    """
    from io import BytesIO

    from PIL import Image, ImageFilter

    zoom = 2.0  # render at 2x for a clean result at print zoom levels
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if mode == "blur":
        # Radius scales with the region so small boxes still smear fully.
        radius = max(10, min(image.width, image.height) // 8)
        image = image.filter(ImageFilter.GaussianBlur(radius))
    else:  # pixelate — ~8pt mosaic blocks regardless of region size
        block = 16
        small = image.resize(
            (max(1, image.width // block), max(1, image.height // block)),
            Image.BILINEAR,
        )
        image = small.resize((image.width, image.height), Image.NEAREST)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _missing_terms_message(missing: list[str], total_terms: int) -> str:
    joined = ", ".join(f'"{term}"' for term in missing)
    if len(missing) == total_terms:
        return (
            f"None of the terms you entered were found in this file: {joined}. "
            "Check the spelling, spacing and letter case, then try again. "
            "(If this is a scanned document, run OCR first so its text becomes "
            "searchable.)"
        )
    return (
        "Redaction was stopped so no sensitive data is left behind: these "
        f"terms were not found and could not be removed — {joined}. Correct or "
        "remove them, then run the tool again."
    )


def redact_text(
    source: Path,
    destination: Path,
    *,
    texts: list[str] | None = None,
    areas: list[dict] | None = None,
) -> int:
    """Permanently remove text matches and/or page areas from a PDF.

    Every occurrence of each string in ``texts`` (case- and, across line
    breaks, layout-insensitive via PyMuPDF's search) is covered with a black
    box, and every rectangle in ``areas`` is covered in its requested style
    (solid black/white/custom fill, or a blurred/pixelated raster of the
    original look). In every style the underlying content is *removed* from
    the document — not merely hidden — via ``apply_redactions``. Surrounding
    layout is preserved (see :func:`_redaction_flags`).

    Fails safe: if any requested term is not found anywhere, the whole job is
    aborted with a message naming the missing terms, so a user is never handed
    a file they believe is clean while a term they typed still sits in it.

    Returns the number of redacted regions.
    """
    import fitz  # PyMuPDF — deferred: heavy import, workers only

    terms = [t.strip() for t in (texts or []) if t and t.strip()]
    # De-duplicate while preserving order, so counts and messages stay clean.
    terms = list(dict.fromkeys(terms))
    area_list = list(areas or [])
    if not terms and not area_list:
        raise ProcessingError("Provide at least one text term or area to redact.")

    try:
        document = fitz.open(str(source))
    except Exception as exc:
        raise ProcessingError(
            f"Could not read the PDF — it may be corrupted or not a valid "
            f"PDF: {exc}"
        ) from exc

    redacted = 0
    try:
        if document.needs_pass:
            raise ProcessingError(
                "This PDF is password-protected. Unlock it with the Unlock PDF "
                "tool first, then redact it."
            )
        if document.page_count == 0:
            raise ProcessingError("The PDF has no pages to redact.")

        areas_by_page = _areas_by_page(area_list, document.page_count)
        term_hits: dict[str, int] = dict.fromkeys(terms, 0)
        flags = _redaction_flags(fitz)

        for index, page in enumerate(document):
            page_regions = 0
            for term in terms:
                rects = page.search_for(term)
                for rect in rects:
                    page.add_redact_annot(rect, fill=(0, 0, 0))
                term_hits[term] += len(rects)
                page_regions += len(rects)
            # Overlays painted after apply_redactions (which strips annots):
            # blurred/pixelated rasters and semi-transparent color fills.
            image_overlays: list[tuple] = []  # (rect, png_bytes)
            fill_overlays: list[tuple] = []  # (rect, rgb, opacity)
            for spec in areas_by_page.get(index, []):
                clipped = fitz.Rect(*spec["rect"]) & page.rect
                if clipped.is_empty:
                    continue
                mode = spec["mode"]
                if mode in ("blur", "pixelate"):
                    # Snapshot the original look before the content beneath
                    # is removed; only this unreadable raster is kept.
                    png = _obscured_region_png(fitz, page, clipped, mode)
                    image_overlays.append((clipped, png))
                    page.add_redact_annot(clipped, fill=(1, 1, 1))
                elif mode == "white":
                    page.add_redact_annot(clipped, fill=(1, 1, 1))
                elif mode == "color":
                    if spec["opacity"] >= 0.999:
                        page.add_redact_annot(clipped, fill=spec["color"])
                    else:
                        # Remove content without a fill, then tint the empty
                        # area with the requested translucent color.
                        page.add_redact_annot(clipped, fill=False)
                        fill_overlays.append(
                            (clipped, spec["color"], spec["opacity"])
                        )
                else:  # black
                    page.add_redact_annot(clipped, fill=(0, 0, 0))
                page_regions += 1
            if page_regions:
                try:
                    page.apply_redactions(**flags)
                except TypeError:  # older PyMuPDF without the graphics keyword
                    page.apply_redactions()
                for rect, png in image_overlays:
                    page.insert_image(rect, stream=png, keep_proportion=False)
                for rect, rgb, opacity in fill_overlays:
                    page.draw_rect(rect, color=None, fill=rgb, fill_opacity=opacity)
                redacted += page_regions

        missing = [term for term, hits in term_hits.items() if hits == 0]
        if missing:
            raise ProcessingError(_missing_terms_message(missing, len(terms)))
        if redacted == 0:
            raise ProcessingError(
                "Nothing was redacted — no matching text or valid areas were "
                "found in this document."
            )

        document.save(str(destination), garbage=3, deflate=True)
    finally:
        document.close()

    logger.info(
        "redaction_complete", regions=redacted, terms=len(terms), areas=len(area_list)
    )
    return redacted


# --------------------------------------------------------------------------- #
# Fill forms (AcroForm)
# --------------------------------------------------------------------------- #
def fill_form(source: Path, destination: Path, *, fields: dict[str, str]) -> int:
    """Fill AcroForm fields by name. Returns how many fields were set."""
    reader = open_pdf(source)
    available = reader.get_fields() or {}
    if not available:
        raise ProcessingError("This PDF has no fillable form fields.")
    matched = {name: value for name, value in fields.items() if name in available}
    if not matched:
        raise ProcessingError(
            "None of the given field names exist. Available fields: "
            + ", ".join(sorted(available)[:20])
        )

    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, matched)
    # Ask viewers to regenerate field appearances so values are visible.
    if writer._root_object.get("/AcroForm") is not None:
        from pypdf.generic import BooleanObject

        writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = (
            BooleanObject(True)
        )
    with destination.open("wb") as handle:
        writer.write(handle)
    return len(matched)
