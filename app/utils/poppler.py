"""Poppler-based PDF rasterisation (``pdftoppm``).

Shared by the PDF→JPG and PDF→PNG tools. One call renders one PDF's pages to
image files inside the caller's workspace and returns them in page order.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from app.config import get_settings
from app.exceptions.jobs import ProcessingError
from app.logging import get_logger
from app.utils.command import run_tool_command, split_launcher

logger = get_logger(__name__)

ImageFormat = Literal["jpeg", "png"]

_EXTENSIONS: dict[ImageFormat, str] = {"jpeg": "jpg", "png": "png"}
_PAGE_SUFFIX = re.compile(r"-(\d+)$")


def pdf_to_images(
    input_path: Path,
    output_dir: Path,
    *,
    image_format: ImageFormat = "jpeg",
    dpi: int = 150,
    quality: int = 90,
    grayscale: bool = False,
    first_page: int | None = None,
    last_page: int | None = None,
    timeout: int | None = None,
    display_name: str | None = None,
) -> list[tuple[int, Path]]:
    """Render a PDF's pages to images; return ``(page_number, path)`` pairs.

    Page numbers reflect the source document (``first_page=3`` yields pages
    numbered from 3), matching what users expect in output filenames.
    ``display_name`` is the user-facing name used in error messages (the
    on-disk ``input_path`` is a storage UUID the user has never seen).
    """
    prefix = output_dir / f"{input_path.stem}-page"
    command = [
        *split_launcher(get_settings().PDFTOPPM_BIN),
        "-jpeg" if image_format == "jpeg" else "-png",
        "-r",
        str(dpi),
    ]
    if image_format == "jpeg":
        command += ["-jpegopt", f"quality={quality}"]
    if grayscale:
        command += ["-gray"]
    if first_page is not None:
        command += ["-f", str(first_page)]
    if last_page is not None:
        command += ["-l", str(last_page)]
    command += [str(input_path), str(prefix)]

    run_tool_command(command, tool_label="PDF renderer", timeout=timeout)

    extension = _EXTENSIONS[image_format]
    pages: list[tuple[int, Path]] = []
    for path in output_dir.glob(f"{prefix.name}-*.{extension}"):
        match = _PAGE_SUFFIX.search(path.stem)
        if match:
            pages.append((int(match.group(1)), path))
    pages.sort(key=lambda item: item[0])

    if not pages:
        raise ProcessingError(
            f"Rendering produced no pages for '{display_name or input_path.name}'. "
            "The file may be corrupted or empty."
        )
    return pages


def pdf_to_images_auto(
    input_path: Path,
    output_dir: Path,
    *,
    total_pages: int,
    image_format: ImageFormat = "jpeg",
    dpi: int = 150,
    quality: int = 90,
    grayscale: bool = False,
    first_page: int | None = None,
    last_page: int | None = None,
    display_name: str | None = None,
) -> list[tuple[int, Path]]:
    """Render pages, splitting large documents into parallel chunks.

    ``pdftoppm`` renders serially; for documents beyond the configured
    threshold this fans page ranges out across a small thread pool, each
    chunk rendering into its own subdirectory (the prefix glob must not see
    other chunks' files).
    """
    settings = get_settings()
    start = first_page or 1
    end = min(last_page or total_pages, total_pages)
    span = max(0, end - start + 1)

    def render_range(range_start: int, range_end: int, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        return pdf_to_images(
            input_path,
            directory,
            image_format=image_format,
            dpi=dpi,
            quality=quality,
            grayscale=grayscale,
            first_page=range_start,
            last_page=range_end,
            display_name=display_name,
        )

    if span <= settings.RENDER_PARALLEL_THRESHOLD_PAGES:
        return render_range(start, end, output_dir)

    workers = max(1, settings.RENDER_PARALLEL_WORKERS)
    chunk_size = -(-span // workers)  # ceil division
    ranges = [
        (chunk_start, min(chunk_start + chunk_size - 1, end))
        for chunk_start in range(start, end + 1, chunk_size)
    ]
    logger.info(
        "parallel_render",
        file=input_path.name,
        pages=span,
        chunks=len(ranges),
        workers=workers,
    )

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(
            executor.map(
                lambda item: render_range(
                    item[1][0], item[1][1], output_dir / f"chunk-{item[0]}"
                ),
                enumerate(ranges),
            )
        )
    pages = [page for chunk in results for page in chunk]
    pages.sort(key=lambda item: item[0])
    return pages
