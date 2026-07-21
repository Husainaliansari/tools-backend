"""PDF overlay engine (reportlab + pypdf).

One generic loop — render a per-page vector overlay with reportlab, merge it
onto the source page with pypdf — powers the Watermark, Header & Footer and
Page Numbers tools. Each tool contributes only a *draw function*.

Also provides ``parse_page_range`` ("1-3,7" → page predicate) and
``parse_page_selection`` (all/first/last/odd/even/custom → page predicate)
shared by every tool that supports page targeting.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from app.exceptions.jobs import ProcessingError

Align = str  # "left" | "center" | "right"

#: Millimetres → PDF points.
MM_TO_PT = 72.0 / 25.4

#: Predicate over (1-based page number, total pages).
PageFilter = Callable[[int, int], bool]

#: reportlab base-14 font names by (family, bold, italic).
_FONT_VARIANTS: dict[str, dict[tuple[bool, bool], str]] = {
    "helvetica": {
        (False, False): "Helvetica",
        (True, False): "Helvetica-Bold",
        (False, True): "Helvetica-Oblique",
        (True, True): "Helvetica-BoldOblique",
    },
    "times": {
        (False, False): "Times-Roman",
        (True, False): "Times-Bold",
        (False, True): "Times-Italic",
        (True, True): "Times-BoldItalic",
    },
    "courier": {
        (False, False): "Courier",
        (True, False): "Courier-Bold",
        (False, True): "Courier-Oblique",
        (True, True): "Courier-BoldOblique",
    },
}


def resolve_font(family: str, *, bold: bool = False, italic: bool = False) -> str:
    """Map a font family + style flags to a reportlab base-14 font name."""
    variants = _FONT_VARIANTS.get(family, _FONT_VARIANTS["helvetica"])
    return variants[(bold, italic)]


@dataclass(frozen=True)
class OverlayPage:
    """What a draw function knows about the page it is drawing on.

    ``width``/``height`` describe the page's *visible* area (its cropbox) —
    draw functions work in a (0, 0)-based coordinate space over that area
    and the engine maps it onto the page.
    """

    number: int  # 1-based page number
    total: int
    width: float  # points
    height: float
    #: Display name of the source document (for the {filename} placeholder).
    filename: str = ""


DrawFn = Callable[[Canvas, OverlayPage], None]


def parse_page_range(spec: str | None) -> PageFilter:
    """Turn '1-3,7' into a predicate over (1-based page number, total).

    ``None``/empty means every page.
    """
    if not spec:
        return lambda _page, _total: True
    selected: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            start, end = part.split("-", 1)
            selected.update(range(int(start), int(end) + 1))
        else:
            selected.add(int(part))
    return lambda page, _total: page in selected


def parse_page_selection(pages: str, page_range: str | None = None) -> PageFilter:
    """Build a page predicate from a selection mode.

    ``pages`` is one of all/first/last/odd/even/custom; ``page_range``
    ("1-3,7") applies in custom mode. A ``page_range`` supplied with the
    default ``all`` selection is honoured too, so callers need not also
    switch the mode to ``custom``.
    """
    if pages == "custom" or (pages == "all" and page_range):
        return parse_page_range(page_range)
    if pages == "first":
        return lambda page, _total: page == 1
    if pages == "last":
        return lambda page, total: page == total
    if pages == "odd":
        return lambda page, _total: page % 2 == 1
    if pages == "even":
        return lambda page, _total: page % 2 == 0
    return lambda _page, _total: True


def _open_reader(source: Path) -> PdfReader:
    try:
        reader = PdfReader(source)
        # Some PDFs are "encrypted" with an empty user password; real
        # passwords are a hard stop.
        if reader.is_encrypted and not reader.decrypt(""):
            raise ProcessingError("The PDF is password-protected. Unlock it first.")
        if len(reader.pages) == 0:
            raise ProcessingError("The PDF contains no pages.")
        return reader
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError(f"Could not read the PDF: {exc}") from exc


def overlay_pdf(
    source: Path,
    destination: Path,
    draw: DrawFn,
    *,
    page_filter: PageFilter | None = None,
    under: bool = False,
    display_name: str = "",
) -> int:
    """Apply ``draw`` to every selected page; write the result. Returns the
    total page count. ``under`` places the overlay below the existing page
    content instead of on top of it. ``display_name`` feeds the {filename}
    placeholder.

    Overlays are positioned relative to the page's *cropbox* — the area a
    viewer actually shows. Positioning against the mediabox instead put
    stamps into the cropped-away region of documents whose cropbox is
    smaller than (or offset within) the mediabox, so they never appeared.
    Pages with a /Rotate flag get the rotation baked into their content
    first so the overlay reads upright in the displayed orientation.
    """
    reader = _open_reader(source)
    writer = PdfWriter()
    total = len(reader.pages)

    for index, page in enumerate(reader.pages):
        number = index + 1
        if page_filter is not None and not page_filter(number, total):
            writer.add_page(page)
            continue

        if (page.rotation or 0) % 360 != 0:
            page.transfer_rotation_to_content()

        crop = page.cropbox
        left = float(crop.left)
        bottom = float(crop.bottom)
        width = float(crop.width)
        height = float(crop.height)
        buffer = io.BytesIO()
        canvas = Canvas(buffer, pagesize=(width, height))
        # merge_page copies coordinates verbatim, so shift the overlay's
        # (0, 0)-based drawing space onto the cropbox origin.
        if left or bottom:
            canvas.translate(left, bottom)
        draw(
            canvas,
            OverlayPage(
                number=number,
                total=total,
                width=width,
                height=height,
                filename=display_name,
            ),
        )
        # Force page emission: a draw fn that drew nothing (e.g. signature on
        # a different page) would otherwise yield a zero-page overlay PDF.
        canvas.showPage()
        canvas.save()

        overlay_page = PdfReader(buffer).pages[0]
        # merge_page clips the overlay to the overlay's *own* cropbox, which
        # reportlab wrote as [0 0 width height]. Re-anchor it onto the target
        # page's crop area so the translated content isn't clipped away.
        overlay_page.mediabox = RectangleObject(
            (left, bottom, left + width, bottom + height)
        )
        page.merge_page(overlay_page, over=not under)
        writer.add_page(page)

    with destination.open("wb") as handle:
        writer.write(handle)
    return total


def substitute_placeholders(template: str, page: OverlayPage) -> str:
    """Expand {page}, {total}, {date}, {time} and {filename} in templates."""
    now = datetime.now(UTC)
    return (
        template.replace("{page}", str(page.number))
        .replace("{total}", str(page.total))
        .replace("{date}", now.strftime("%Y-%m-%d"))
        .replace("{time}", now.strftime("%H:%M"))
        .replace("{filename}", page.filename)
    )


# --------------------------------------------------------------------------- #
# Draw-function factories used by the tools
# --------------------------------------------------------------------------- #
def _anchor_point(
    position: str,
    page_width: float,
    page_height: float,
    block_width: float,
    block_height: float,
    margin_pt: float,
    offset_x_pt: float,
    offset_y_pt: float,
) -> tuple[float, float]:
    """Centre point for a block anchored to one of the nine grid positions.

    Offsets follow screen conventions: +x nudges right, +y nudges down.
    """
    if position == "center":
        vertical = horizontal = "center"
    else:
        vertical, _, horizontal = position.partition("-")

    if horizontal == "left":
        x = margin_pt + block_width / 2
    elif horizontal == "right":
        x = page_width - margin_pt - block_width / 2
    else:
        x = page_width / 2

    if vertical == "top":
        y = page_height - margin_pt - block_height / 2
    elif vertical == "bottom":
        y = margin_pt + block_height / 2
    else:
        y = page_height / 2

    return x + offset_x_pt, y - offset_y_pt


def _stamp_grid(
    canvas: Canvas,
    page: OverlayPage,
    rotation: int,
    step_x: float,
    step_y: float,
    stamp: Callable[[float, float], None],
) -> None:
    """Tile ``stamp`` in a brick-staggered grid rotated about the page centre."""
    canvas.translate(page.width / 2, page.height / 2)
    canvas.rotate(rotation)
    span = max(page.width, page.height)
    y = -span
    row = 0
    while y <= span:
        offset = (row % 2) * step_x / 2  # brick-like stagger
        x = -span + offset
        while x <= span:
            stamp(x, y)
            x += step_x
        y += step_y
        row += 1


def make_watermark_draw(
    text: str,
    *,
    font_size: int,
    opacity: float,
    rotation: int,
    color: str,
    tile: bool,
    font_family: str = "helvetica",
    bold: bool = True,
    italic: bool = False,
    underline: bool = False,
    align: Align = "center",
    letter_spacing: float = 0.0,
    line_height: float = 1.2,
    position: str = "center",
    offset_x_pt: float = 0.0,
    offset_y_pt: float = 0.0,
    margin_pt: float = 12.0 * MM_TO_PT,
) -> DrawFn:
    """Styled (multi-line) text watermark anchored to a 3×3 grid position;
    ``tile`` repeats it across the whole page instead."""
    font = resolve_font(font_family, bold=bold, italic=italic)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    widths = [
        stringWidth(line, font, font_size) + letter_spacing * max(len(line) - 1, 0)
        for line in lines
    ]
    block_width = max(widths)
    line_step = font_size * line_height
    block_height = font_size + line_step * (len(lines) - 1)

    def draw_block(canvas: Canvas, cx: float, cy: float) -> None:
        """Draw the text block centred on (cx, cy) in canvas coordinates."""
        ascent = font_size * 0.75
        top = cy + block_height / 2
        for index, (line, width) in enumerate(zip(lines, widths, strict=True)):
            baseline = top - ascent - index * line_step
            if align == "left":
                x = cx - block_width / 2
            elif align == "right":
                x = cx + block_width / 2 - width
            else:
                x = cx - width / 2
            canvas.drawString(x, baseline, line, charSpace=letter_spacing)
            if underline and line.strip():
                rule_y = baseline - font_size * 0.1
                canvas.setLineWidth(max(font_size * 0.05, 0.5))
                canvas.line(x, rule_y, x + width, rule_y)

    def draw(canvas: Canvas, page: OverlayPage) -> None:
        canvas.saveState()
        canvas.setFont(font, font_size)
        canvas.setFillColor(HexColor(color))
        canvas.setStrokeColor(HexColor(color))
        canvas.setFillAlpha(opacity)
        canvas.setStrokeAlpha(opacity)
        if tile:
            step_x = block_width + max(font_size * 2.0, 48.0)
            step_y = block_height + max(font_size * 1.6, 48.0)
            _stamp_grid(
                canvas,
                page,
                rotation,
                step_x,
                step_y,
                lambda x, y: draw_block(canvas, x, y),
            )
        else:
            anchor_x, anchor_y = _anchor_point(
                position,
                page.width,
                page.height,
                block_width,
                block_height,
                margin_pt,
                offset_x_pt,
                offset_y_pt,
            )
            canvas.translate(anchor_x, anchor_y)
            canvas.rotate(rotation)
            draw_block(canvas, 0, 0)
        canvas.restoreState()

    return draw


def make_image_watermark_draw(
    image_path: Path,
    *,
    opacity: float,
    rotation: int,
    scale: float,
    position: str = "center",
    offset_x_pt: float = 0.0,
    offset_y_pt: float = 0.0,
    margin_pt: float = 12.0 * MM_TO_PT,
    tile: bool = False,
    keep_aspect: bool = True,
    scale_x: float | None = None,
    scale_y: float | None = None,
) -> DrawFn:
    """Image watermark anchored to a 3×3 grid position; ``tile`` repeats it.

    With ``keep_aspect``, ``scale`` is the fraction of the page's short side
    the image's larger dimension occupies. Without it, ``scale_x``/``scale_y``
    stretch the image to those fractions of the page width/height.
    """
    image = ImageReader(str(image_path))
    image_width, image_height = image.getSize()

    def draw(canvas: Canvas, page: OverlayPage) -> None:
        if keep_aspect:
            target = min(page.width, page.height) * scale
            ratio = target / max(image_width, image_height)
            draw_width = image_width * ratio
            draw_height = image_height * ratio
        else:
            draw_width = page.width * (scale_x if scale_x is not None else scale)
            draw_height = page.height * (scale_y if scale_y is not None else scale)

        def stamp(x: float, y: float) -> None:
            canvas.drawImage(
                image,
                x - draw_width / 2,
                y - draw_height / 2,
                width=draw_width,
                height=draw_height,
                mask="auto",
            )

        canvas.saveState()
        canvas.setFillAlpha(opacity)
        if tile:
            _stamp_grid(
                canvas, page, rotation, draw_width * 1.5, draw_height * 1.5, stamp
            )
        else:
            anchor_x, anchor_y = _anchor_point(
                position,
                page.width,
                page.height,
                draw_width,
                draw_height,
                margin_pt,
                offset_x_pt,
                offset_y_pt,
            )
            canvas.translate(anchor_x, anchor_y)
            canvas.rotate(rotation)
            stamp(0, 0)
        canvas.restoreState()

    return draw


def make_signature_draw(
    image_path: Path,
    *,
    target_page: int | None,
    position: str,
    scale: float,
    margin_pt: float,
) -> DrawFn:
    """Place a signature image on one page (None = last page).

    ``position`` is one of the six corner/center anchors used by the
    page-number tool.
    """
    image = ImageReader(str(image_path))
    image_width, image_height = image.getSize()

    def draw(canvas: Canvas, page: OverlayPage) -> None:
        target = target_page if target_page is not None else page.total
        if page.number != target:
            return
        draw_width = page.width * scale
        draw_height = draw_width * image_height / image_width

        vertical, _, horizontal = position.partition("-")
        y = page.height - margin_pt - draw_height if vertical == "top" else margin_pt
        if horizontal == "left":
            x = margin_pt
        elif horizontal == "right":
            x = page.width - margin_pt - draw_width
        else:
            x = (page.width - draw_width) / 2

        canvas.drawImage(image, x, y, width=draw_width, height=draw_height, mask="auto")

    return draw


def make_header_footer_draw(
    header_text: str | None,
    footer_text: str | None,
    *,
    font_size: int,
    color: str,
    margin_pt: float,
    align: Align = "center",
    header_align: Align | None = None,
    footer_align: Align | None = None,
    font_family: str = "helvetica",
    bold: bool = False,
    italic: bool = False,
    opacity: float = 1.0,
) -> DrawFn:
    """Header at the top margin, footer at the bottom; both optional.

    ``align`` is the shared default; ``header_align``/``footer_align``
    override it per line.
    """
    font = resolve_font(font_family, bold=bold, italic=italic)

    def draw(canvas: Canvas, page: OverlayPage) -> None:
        canvas.saveState()
        canvas.setFont(font, font_size)
        canvas.setFillColor(HexColor(color))
        canvas.setFillAlpha(opacity)
        for text, y, line_align in (
            (header_text, page.height - margin_pt, header_align or align),
            (footer_text, margin_pt - font_size * 0.2, footer_align or align),
        ):
            if not text:
                continue
            rendered = substitute_placeholders(text, page)
            if line_align == "left":
                canvas.drawString(margin_pt, y, rendered)
            elif line_align == "right":
                canvas.drawRightString(page.width - margin_pt, y, rendered)
            else:
                canvas.drawCentredString(page.width / 2, y, rendered)
        canvas.restoreState()

    return draw


def make_page_number_draw(
    template: str,
    *,
    position: str,
    font_size: int,
    color: str,
    margin_pt: float,
    number_offset: int,
) -> DrawFn:
    """Page number stamp at one of six positions.

    ``number_offset`` shifts displayed numbers (start_at=5 → offset 4).
    """

    def draw(canvas: Canvas, page: OverlayPage) -> None:
        shifted = OverlayPage(
            number=page.number + number_offset,
            total=page.total + number_offset,
            width=page.width,
            height=page.height,
        )
        rendered = substitute_placeholders(template, shifted)
        vertical, _, horizontal = position.partition("-")
        y = (
            page.height - margin_pt
            if vertical == "top"
            else margin_pt - font_size * 0.2
        )
        canvas.saveState()
        canvas.setFont("Helvetica", font_size)
        canvas.setFillColor(HexColor(color))
        if horizontal == "left":
            canvas.drawString(margin_pt, y, rendered)
        elif horizontal == "right":
            canvas.drawRightString(page.width - margin_pt, y, rendered)
        else:
            canvas.drawCentredString(page.width / 2, y, rendered)
        canvas.restoreState()

    return draw
