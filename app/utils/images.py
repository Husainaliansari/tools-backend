"""Image → PDF assembly (img2pdf + Pillow).

img2pdf embeds JPEG data losslessly (no recompression, no quality loss, small
output) and respects EXIF orientation. Two cases it cannot take directly are
normalised with Pillow first:

* images with an alpha channel (flattened onto white),
* palette/exotic modes (converted to RGB).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

import img2pdf
from PIL import Image

from app.exceptions.jobs import ProcessingError
from app.logging import get_logger

logger = get_logger(__name__)

PageSize = Literal["fit", "a4", "letter"]
Orientation = Literal["portrait", "landscape"]

_PAGE_SIZES_MM: dict[str, tuple[float, float]] = {
    "a4": (210.0, 297.0),
    "letter": (215.9, 279.4),
}


def _normalise(path: Path) -> bytes:
    """Return image bytes img2pdf can embed; flatten alpha, fix odd modes."""
    data = path.read_bytes()
    with Image.open(io.BytesIO(data)) as image:
        has_alpha = image.mode in ("RGBA", "LA", "PA") or (
            image.mode == "P" and "transparency" in image.info
        )
        if not has_alpha and image.mode in ("RGB", "L", "1", "CMYK"):
            return data  # img2pdf can embed the original losslessly

        converted = image.convert("RGBA") if has_alpha else image.convert("RGB")
        if has_alpha:
            background = Image.new("RGB", converted.size, (255, 255, 255))
            background.paste(converted, mask=converted.getchannel("A"))
            converted = background
        buffer = io.BytesIO()
        converted.save(buffer, format="PNG")
        return buffer.getvalue()


def images_to_pdf(
    image_paths: list[Path],
    output_path: Path,
    *,
    page_size: PageSize = "fit",
    orientation: Orientation = "portrait",
    margin_mm: float = 10.0,
) -> Path:
    """Combine images into one PDF, in order. Returns ``output_path``.

    ``fit`` sizes each page to its image; fixed sizes (a4/letter) centre the
    image within the page minus margins.
    """
    if not image_paths:
        raise ProcessingError("No images to combine.")

    layout_fun = None
    if page_size != "fit":
        width_mm, height_mm = _PAGE_SIZES_MM[page_size]
        if orientation == "landscape":
            width_mm, height_mm = height_mm, width_mm
        margin_pt = img2pdf.mm_to_pt(margin_mm)
        layout_fun = img2pdf.get_layout_fun(
            pagesize=(img2pdf.mm_to_pt(width_mm), img2pdf.mm_to_pt(height_mm)),
            border=(margin_pt, margin_pt),  # (vertical, horizontal)
        )

    try:
        payload = [_normalise(path) for path in image_paths]
        kwargs = {"rotation": img2pdf.Rotation.ifvalid}
        if layout_fun is not None:
            kwargs["layout_fun"] = layout_fun
        output_path.write_bytes(img2pdf.convert(payload, **kwargs))
    except ProcessingError:
        raise
    except Exception as exc:  # img2pdf raises assorted exception types
        raise ProcessingError(
            f"Could not build a PDF from the supplied images: {exc}"
        ) from exc
    return output_path
