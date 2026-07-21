"""Unit tests for pypdf page operations (real PDFs)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from app.exceptions.jobs import ProcessingError
from app.utils import pdf_pages
from tests.fixtures.factories import make_pdf_bytes


@pytest.fixture()
def pdf3(tmp_path: Path) -> Path:
    path = tmp_path / "three.pdf"
    path.write_bytes(make_pdf_bytes(pages=3))
    return path


class TestParsePageSelection:
    def test_mixed_selection(self):
        assert pdf_pages.parse_page_selection("1,3-5", 10) == [1, 3, 4, 5]

    def test_out_of_range_rejected(self):
        with pytest.raises(ProcessingError, match="out of range"):
            pdf_pages.parse_page_selection("1,7", 3)

    def test_garbage_rejected(self):
        with pytest.raises(ProcessingError, match="Invalid"):
            pdf_pages.parse_page_selection("a-b", 3)


class TestPageOperations:
    def test_merge(self, tmp_path, pdf3):
        second = tmp_path / "two.pdf"
        second.write_bytes(make_pdf_bytes(pages=2))
        out = pdf_pages.merge_pdfs([pdf3, second], tmp_path / "merged.pdf")
        assert len(PdfReader(out).pages) == 5

    def test_split_ranges(self, tmp_path, pdf3):
        parts = pdf_pages.split_pdf(pdf3, tmp_path, ranges=["1-2", "3"])
        assert len(parts) == 2
        assert len(PdfReader(parts[0][1]).pages) == 2
        assert len(PdfReader(parts[1][1]).pages) == 1

    def test_split_every_page(self, tmp_path, pdf3):
        parts = pdf_pages.split_pdf(pdf3, tmp_path, every_page=True)
        assert len(parts) == 3

    def test_rotate_selected_pages(self, tmp_path, pdf3):
        out = pdf_pages.rotate_pdf(pdf3, tmp_path / "rot.pdf", angle=90, pages="2")
        reader = PdfReader(out)
        assert reader.pages[0].rotation == 0
        assert reader.pages[1].rotation == 90

    def test_rotate_even_pages(self, tmp_path, pdf3):
        out = pdf_pages.rotate_pdf(
            pdf3, tmp_path / "rot.pdf", angle=180, apply_to="even"
        )
        reader = PdfReader(out)
        assert [p.rotation for p in reader.pages] == [0, 180, 0]

    def test_delete_pages(self, tmp_path, pdf3):
        out = pdf_pages.delete_pages(pdf3, tmp_path / "del.pdf", pages="2")
        reader = PdfReader(out)
        assert len(reader.pages) == 2
        texts = [p.extract_text() for p in reader.pages]
        assert "Body text 2" not in " ".join(texts)

    def test_delete_all_pages_rejected(self, tmp_path, pdf3):
        with pytest.raises(ProcessingError, match="every page"):
            pdf_pages.delete_pages(pdf3, tmp_path / "x.pdf", pages="1-3")

    def test_extract_pages_in_order(self, tmp_path, pdf3):
        out = pdf_pages.extract_pages(pdf3, tmp_path / "ex.pdf", pages="3,1")
        reader = PdfReader(out)
        assert "Body text 3" in reader.pages[0].extract_text()
        assert "Body text 1" in reader.pages[1].extract_text()

    def test_reorder(self, tmp_path, pdf3):
        out = pdf_pages.reorder_pages(pdf3, tmp_path / "re.pdf", order=[2, 3, 1])
        reader = PdfReader(out)
        assert "Body text 2" in reader.pages[0].extract_text()

    def test_reorder_invalid_permutation(self, tmp_path, pdf3):
        with pytest.raises(ProcessingError, match="permutation"):
            pdf_pages.reorder_pages(pdf3, tmp_path / "x.pdf", order=[1, 1, 2])

    def test_unlock_roundtrip(self, tmp_path, pdf3):
        locked = tmp_path / "locked.pdf"
        writer = PdfWriter(clone_from=io.BytesIO(pdf3.read_bytes()))
        writer.encrypt(user_password="pw123", algorithm="AES-256")
        with locked.open("wb") as handle:
            writer.write(handle)

        out = pdf_pages.unlock_pdf(locked, tmp_path / "open.pdf", password="pw123")
        assert not PdfReader(out).is_encrypted

    def test_unlock_wrong_password(self, tmp_path, pdf3):
        locked = tmp_path / "locked.pdf"
        writer = PdfWriter(clone_from=io.BytesIO(pdf3.read_bytes()))
        writer.encrypt(user_password="pw123", algorithm="AES-256")
        with locked.open("wb") as handle:
            writer.write(handle)

        with pytest.raises(ProcessingError, match="Incorrect password"):
            pdf_pages.unlock_pdf(locked, tmp_path / "x.pdf", password="nope")

    def test_unlock_unencrypted_rejected(self, tmp_path, pdf3):
        with pytest.raises(ProcessingError, match="not password-protected"):
            pdf_pages.unlock_pdf(pdf3, tmp_path / "x.pdf", password="whatever")
