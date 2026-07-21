"""Unit tests for filename utilities."""

from __future__ import annotations

from app.utils.filenames import (
    file_extension,
    generate_stored_name,
    human_readable_size,
    sanitize_filename,
)


class TestSanitizeFilename:
    def test_plain_name_passes_through(self):
        assert sanitize_filename("report.pdf") == "report.pdf"

    def test_strips_posix_directory_components(self):
        assert sanitize_filename("../../etc/passwd") == "passwd"

    def test_strips_windows_directory_components(self):
        assert sanitize_filename("C:\\Users\\evil\\doc.pdf") == "doc.pdf"

    def test_replaces_unsafe_characters(self):
        assert sanitize_filename('a<b>:c".pdf') == "a_b__c_.pdf"

    def test_windows_reserved_names_are_suffixed(self):
        assert sanitize_filename("CON.pdf") == "CON_.pdf"

    def test_empty_name_falls_back(self):
        assert sanitize_filename("") == "file"
        assert sanitize_filename("...") == "file"

    def test_long_names_keep_extension(self):
        name = sanitize_filename("a" * 500 + ".pdf")
        assert name.endswith(".pdf")
        assert len(name) <= 205


class TestFileExtension:
    def test_lowercases(self):
        assert file_extension("Report.PDF") == "pdf"

    def test_no_extension(self):
        assert file_extension("README") == ""

    def test_ignores_directories_with_dots(self):
        assert file_extension("some.dir/file.docx") == "docx"


class TestGenerateStoredName:
    def test_includes_extension(self):
        assert generate_stored_name("pdf").endswith(".pdf")

    def test_unique(self):
        assert generate_stored_name("pdf") != generate_stored_name("pdf")


class TestHumanReadableSize:
    def test_bytes(self):
        assert human_readable_size(512) == "512 B"

    def test_megabytes(self):
        assert human_readable_size(int(2.4 * 1024 * 1024)) == "2.4 MB"
