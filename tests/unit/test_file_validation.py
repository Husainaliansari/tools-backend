"""Unit tests for upload validation (count, extension, magic bytes)."""

from __future__ import annotations

import pytest

from app.exceptions.files import (
    FileCorruptedError,
    TooManyFilesError,
    UnsupportedFileTypeError,
)
from app.services.file_validation import (
    SUPPORTED_TYPES,
    validate_file_count,
    validate_file_type,
)

PDF_HEAD = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
ZIP_HEAD = b"PK\x03\x04" + b"\x00" * 26
OLE2_HEAD = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 24
JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class TestValidateFileCount:
    def test_zero_files_rejected(self):
        with pytest.raises(UnsupportedFileTypeError):
            validate_file_count(0)

    def test_within_limit_passes(self):
        validate_file_count(3)

    def test_over_limit_rejected(self):
        with pytest.raises(TooManyFilesError):
            validate_file_count(1000)


class TestValidateFileType:
    @pytest.mark.parametrize(
        ("filename", "head", "media_type"),
        [
            ("doc.pdf", PDF_HEAD, "application/pdf"),
            (
                "doc.docx",
                ZIP_HEAD,
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document",
            ),
            ("legacy.doc", OLE2_HEAD, "application/msword"),
            (
                "sheet.xlsx",
                ZIP_HEAD,
                "application/vnd.openxmlformats-officedocument" ".spreadsheetml.sheet",
            ),
            ("legacy.xls", OLE2_HEAD, "application/vnd.ms-excel"),
            ("photo.jpg", JPEG_HEAD, "image/jpeg"),
            ("photo.jpeg", JPEG_HEAD, "image/jpeg"),
            ("image.png", PNG_HEAD, "image/png"),
        ],
    )
    def test_supported_types_pass(self, filename, head, media_type):
        spec = validate_file_type(filename, head)
        assert spec.media_type == media_type

    def test_unknown_extension_rejected(self):
        with pytest.raises(UnsupportedFileTypeError):
            validate_file_type("script.exe", b"MZ\x90\x00")

    def test_extension_not_in_tool_allowlist_rejected(self):
        with pytest.raises(UnsupportedFileTypeError):
            validate_file_type("photo.png", PNG_HEAD, allowed_extensions={"pdf"})

    def test_magic_bytes_mismatch_rejected(self):
        # A renamed executable claiming to be a PDF must be caught.
        with pytest.raises(FileCorruptedError):
            validate_file_type("fake.pdf", b"MZ\x90\x00" + b"\x00" * 100)

    def test_renamed_executable_as_office_rejected(self):
        with pytest.raises(FileCorruptedError):
            validate_file_type("fake.pptx", b"MZ\x90\x00" + b"\x00" * 100)

    @pytest.mark.parametrize(
        ("filename", "head"),
        [
            # OOXML content under a legacy extension (renamed pptx → ppt).
            ("renamed.ppt", ZIP_HEAD),
            ("renamed.xls", ZIP_HEAD),
            ("renamed.doc", ZIP_HEAD),
            # OLE content under an OOXML extension: legacy renames and
            # password-protected OOXML (an OLE wrapper) both look like this.
            ("wrapped.pptx", OLE2_HEAD),
            ("wrapped.xlsx", OLE2_HEAD),
            ("wrapped.docx", OLE2_HEAD),
        ],
    )
    def test_office_container_mismatch_accepted(self, filename, head):
        # PowerPoint/Excel/Word open these by sniffing content; so must we.
        ext = filename.rsplit(".", 1)[1]
        assert validate_file_type(filename, head).extension == ext

    def test_pdf_marker_after_junk_prefix_accepted(self):
        head = b"\n\n junk " + PDF_HEAD
        assert validate_file_type("weird.pdf", head).extension == "pdf"

    def test_all_roadmap_formats_supported(self):
        for ext in ("pdf", "doc", "docx", "xls", "xlsx"):
            assert ext in SUPPORTED_TYPES
