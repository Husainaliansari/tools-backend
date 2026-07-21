"""Upload validation.

Three independent checks, all of which must pass before a byte is persisted:

1. **Count** — the batch size respects ``MAX_FILES_PER_UPLOAD``.
2. **Type** — the extension is in the allow-list *and* the leading bytes match
   that type's magic signature. The client's Content-Type header is ignored:
   it is trivially spoofable, whereas magic bytes require the file to actually
   be what it claims.
3. **Size** — enforced while streaming (see storage service); declared sizes
   are never trusted.

The allow-list covers every format the tool roadmap needs; individual tools
narrow it further (e.g. Merge accepts only PDFs) via ``allowed_extensions``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.config import get_settings
from app.exceptions.files import (
    FileCorruptedError,
    TooManyFilesError,
    UnsupportedFileTypeError,
)
from app.schemas.response import ErrorDetail
from app.utils.filenames import file_extension

# How many leading bytes are needed to identify any supported type.
SNIFF_SIZE = 1024


def _is_pdf(head: bytes) -> bool:
    # Standards-compliant PDFs start with %PDF-, but some generators prepend
    # junk; accept the marker anywhere in the first kilobyte (as PDF readers do).
    return b"%PDF-" in head[:SNIFF_SIZE]


def _is_zip(head: bytes) -> bool:
    # OOXML formats (docx/xlsx/pptx) are ZIP containers.
    return head.startswith(b"PK\x03\x04")


def _is_ole2(head: bytes) -> bool:
    # Legacy Office formats (doc/xls/ppt) use the OLE2 compound document format.
    return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def _is_office(head: bytes) -> bool:
    # Any Office extension accepts either container: extension↔container
    # mismatches are routine in the wild (files renamed between .ppt/.pptx,
    # exports mislabelled by third-party tools, password-protected OOXML —
    # which is an OLE wrapper around the encrypted ZIP). Office and
    # LibreOffice both sniff the real format from content, so rejecting on
    # the extension's "expected" container refuses files that open fine.
    return _is_zip(head) or _is_ole2(head)


def _is_jpeg(head: bytes) -> bool:
    return head.startswith(b"\xff\xd8\xff")


def _is_png(head: bytes) -> bool:
    return head.startswith(b"\x89PNG\r\n\x1a\n")


@dataclass(frozen=True)
class FileTypeSpec:
    """One supported upload type."""

    extension: str
    media_type: str
    matches: Callable[[bytes], bool]


SUPPORTED_TYPES: dict[str, FileTypeSpec] = {
    spec.extension: spec
    for spec in (
        FileTypeSpec("pdf", "application/pdf", _is_pdf),
        FileTypeSpec("doc", "application/msword", _is_office),
        FileTypeSpec(
            "docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _is_office,
        ),
        FileTypeSpec("xls", "application/vnd.ms-excel", _is_office),
        FileTypeSpec(
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            _is_office,
        ),
        FileTypeSpec("ppt", "application/vnd.ms-powerpoint", _is_office),
        FileTypeSpec(
            "pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            _is_office,
        ),
        FileTypeSpec("jpg", "image/jpeg", _is_jpeg),
        FileTypeSpec("jpeg", "image/jpeg", _is_jpeg),
        FileTypeSpec("png", "image/png", _is_png),
    )
}


def validate_file_count(count: int, *, max_files: int | None = None) -> None:
    """Reject empty or oversized upload batches."""
    settings = get_settings()
    limit = max_files or settings.MAX_FILES_PER_UPLOAD
    if count == 0:
        raise UnsupportedFileTypeError("No files were provided.")
    if count > limit:
        raise TooManyFilesError(
            f"At most {limit} files may be uploaded at once (received {count})."
        )


def validate_file_type(
    filename: str,
    head: bytes,
    *,
    allowed_extensions: frozenset[str] | set[str] | None = None,
) -> FileTypeSpec:
    """Validate extension + magic bytes; return the resolved type spec."""
    extension = file_extension(filename)
    spec = SUPPORTED_TYPES.get(extension)

    allowed = allowed_extensions or set(SUPPORTED_TYPES)
    if spec is None or extension not in allowed:
        raise UnsupportedFileTypeError(
            f"File type '.{extension or '?'}' is not supported.",
            details=[
                ErrorDetail(
                    message=f"Allowed types: {', '.join(sorted(allowed))}.",
                    field="files",
                    type="unsupported_file_type",
                )
            ],
        )

    if not spec.matches(head):  # type: ignore[operator]
        raise FileCorruptedError(
            f"'{filename}' does not look like a valid .{extension} file."
        )
    return spec
