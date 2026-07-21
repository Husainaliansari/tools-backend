"""Thumbnail generation for stored files.

Thumbnails are generated on first request and cached on disk under
``thumbnails/<file_id>.jpg`` — no database row, cheap to regenerate, removed
implicitly when the storage tree is cleaned.

PDFs render their first page via Poppler; images downscale via Pillow.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.config import get_settings
from app.exceptions.files import UnsupportedFileTypeError
from app.exceptions.jobs import ProcessingError
from app.models.file import StoredFile
from app.services.storage import LocalStorageService
from app.services.temp_files import temp_workspace
from app.utils.poppler import pdf_to_images

THUMBNAIL_MAX_EDGE = 320
_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}


def thumbnail_path(file_id: str) -> Path:
    return get_settings().THUMBNAILS_DIR / f"{file_id}.jpg"


def generate_thumbnail(record: StoredFile, storage: LocalStorageService) -> Path:
    """Create (or return the cached) JPEG thumbnail for a stored file.

    Synchronous and CPU/subprocess bound — call it from a worker thread.
    """
    target = thumbnail_path(str(record.id))
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)

    source = storage.resolve(record.category, record.relative_path)

    if record.extension == "pdf":
        with temp_workspace(prefix="thumb") as workspace:
            pages = pdf_to_images(
                source,
                workspace,
                image_format="jpeg",
                dpi=40,
                quality=70,
                first_page=1,
                last_page=1,
            )
            _, first_page_path = pages[0]
            _downscale(first_page_path, target)
        return target

    if record.extension in _IMAGE_EXTENSIONS:
        _downscale(source, target)
        return target

    raise UnsupportedFileTypeError(
        f"No thumbnail available for .{record.extension} files."
    )


def _downscale(source: Path, target: Path) -> None:
    try:
        with Image.open(source) as image:
            image.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE))
            image.convert("RGB").save(target, format="JPEG", quality=80)
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError(f"Could not build a thumbnail: {exc}") from exc
