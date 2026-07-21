"""Page-level PDF operations (pypdf): merge, split, rotate, delete, extract,
reorder, unlock.

Pure-Python and deterministic — these are the engines behind the Organize
tools. All functions raise :class:`ProcessingError` on user-caused problems
(bad ranges, wrong passwords, corrupt files) so the worker surfaces them as
job errors rather than crashes.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from app.exceptions.jobs import ProcessingError


def open_pdf(source: Path, *, password: str | None = None) -> PdfReader:
    """Open a PDF, transparently handling empty-password encryption."""
    try:
        reader = PdfReader(source)
    except Exception as exc:
        raise ProcessingError(f"Could not read the PDF: {exc}") from exc
    if reader.is_encrypted and reader.decrypt(password or "") == 0:
        raise ProcessingError(
            "The PDF is password-protected."
            if password is None
            else "Incorrect password for this PDF."
        )
    if len(reader.pages) == 0:
        raise ProcessingError("The PDF contains no pages.")
    return reader


def page_count(source: Path) -> int:
    return len(open_pdf(source).pages)


def parse_page_selection(spec: str, total: int) -> list[int]:
    """Parse '1,3-5' into an ordered, validated list of 1-based page numbers."""
    pages: list[int] = []
    try:
        for part in spec.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                start, end = (int(x) for x in part.split("-", 1))
                pages.extend(range(start, end + 1))
            else:
                pages.append(int(part))
    except ValueError as exc:
        raise ProcessingError(f"Invalid page selection '{spec}'.") from exc
    if not pages:
        raise ProcessingError("The page selection is empty.")
    out_of_range = [p for p in pages if p < 1 or p > total]
    if out_of_range:
        raise ProcessingError(
            f"Pages {sorted(set(out_of_range))} are out of range "
            f"(document has {total} pages)."
        )
    return pages


def _write(writer: PdfWriter, destination: Path) -> Path:
    with destination.open("wb") as handle:
        writer.write(handle)
    return destination


def merge_pdfs(sources: list[Path], destination: Path) -> Path:
    """Concatenate PDFs in order, preserving bookmarks per document."""
    writer = PdfWriter()
    for source in sources:
        reader = open_pdf(source)
        writer.append(reader)
    return _write(writer, destination)


def split_pdf(
    source: Path,
    output_dir: Path,
    *,
    ranges: list[str] | None = None,
    every_page: bool = False,
) -> list[tuple[str, Path]]:
    """Split into parts; returns ``(label, path)`` pairs in output order.

    Either explicit ``ranges`` (each producing one part) or ``every_page``.
    """
    reader = open_pdf(source)
    total = len(reader.pages)
    parts: list[tuple[str, Path]] = []

    if every_page:
        selections = [(str(n), [n]) for n in range(1, total + 1)]
    elif ranges:
        selections = [(spec, parse_page_selection(spec, total)) for spec in ranges]
    else:
        raise ProcessingError("Provide page ranges or choose every-page mode.")

    for index, (label, pages) in enumerate(selections):
        writer = PdfWriter()
        for number in pages:
            writer.add_page(reader.pages[number - 1])
        path = _write(writer, output_dir / f"part-{index + 1}.pdf")
        parts.append((label.replace(",", "_"), path))
    return parts


def rotate_pdf(
    source: Path,
    destination: Path,
    *,
    angle: int,
    pages: str | None = None,
    apply_to: str = "all",  # all | odd | even
) -> Path:
    """Rotate pages clockwise by 90/180/270 degrees."""
    if angle % 90 != 0 or angle % 360 == 0:
        raise ProcessingError("Rotation must be 90, 180 or 270 degrees.")
    reader = open_pdf(source)
    total = len(reader.pages)
    selected = set(parse_page_selection(pages, total)) if pages else None

    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        number = index + 1
        matches = (
            (selected is None or number in selected)
            and (apply_to != "odd" or number % 2 == 1)
            and (apply_to != "even" or number % 2 == 0)
        )
        if matches:
            page.rotate(angle)
        writer.add_page(page)
    return _write(writer, destination)


def delete_pages(source: Path, destination: Path, *, pages: str) -> Path:
    """Remove the selected pages; at least one page must remain."""
    reader = open_pdf(source)
    total = len(reader.pages)
    doomed = set(parse_page_selection(pages, total))
    if len(doomed) >= total:
        raise ProcessingError("Cannot delete every page of the document.")
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index + 1 not in doomed:
            writer.add_page(page)
    return _write(writer, destination)


def extract_pages(source: Path, destination: Path, *, pages: str) -> Path:
    """Build a new PDF from the selected pages, in the order given."""
    reader = open_pdf(source)
    selection = parse_page_selection(pages, len(reader.pages))
    writer = PdfWriter()
    for number in selection:
        writer.add_page(reader.pages[number - 1])
    return _write(writer, destination)


def reorder_pages(source: Path, destination: Path, *, order: list[int]) -> Path:
    """Rearrange pages; ``order`` must be a permutation of 1..N."""
    reader = open_pdf(source)
    total = len(reader.pages)
    if sorted(order) != list(range(1, total + 1)):
        raise ProcessingError(
            f"Order must be a permutation of pages 1-{total} (got {order})."
        )
    writer = PdfWriter()
    for number in order:
        writer.add_page(reader.pages[number - 1])
    return _write(writer, destination)


def unlock_pdf(source: Path, destination: Path, *, password: str) -> Path:
    """Remove encryption using the supplied password."""
    reader = open_pdf(source, password=password)
    if not reader.is_encrypted:
        raise ProcessingError("This PDF is not password-protected.")
    writer = PdfWriter()
    writer.append(reader)
    return _write(writer, destination)
