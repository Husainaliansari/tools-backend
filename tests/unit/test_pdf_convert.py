"""Unit tests for the PDF→Word pre-flight and fallback conversion paths.

Uses real PDFs built in-test with PyMuPDF/pikepdf — the failure modes under
test (encryption, damaged structure) live in the file format itself and
cannot be faked meaningfully.
"""

from __future__ import annotations

import pytest

from app.exceptions.jobs import ProcessingError
from app.utils.pdf_convert import (
    _fallback_pdf_to_docx,
    pdf_to_docx,
    prepare_pdf_for_conversion,
)


@pytest.fixture
def text_pdf(tmp_path):
    """A small, clean, unencrypted PDF with real text content."""
    import fitz

    path = tmp_path / "clean.pdf"
    doc = fitz.open()
    for number in range(2):
        page = doc.new_page()
        page.insert_text((72, 100), f"Hello page {number + 1}", fontsize=14)
    doc.save(str(path))
    doc.close()
    return path


def _encrypt(source, target, *, owner: str, user: str) -> None:
    import pikepdf

    with pikepdf.open(source) as pdf:
        pdf.save(
            target,
            encryption=pikepdf.Encryption(owner=owner, user=user, R=6),
        )


class TestPreparePdfForConversion:
    def test_clean_pdf_returned_untouched(self, text_pdf, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        assert prepare_pdf_for_conversion(text_pdf, workspace) == text_pdf
        assert not list(workspace.iterdir())  # no needless copies

    def test_owner_password_pdf_passes_through(self, text_pdf, tmp_path):
        """Owner-password PDFs auto-authenticate in PyMuPDF (pdf2docx reads
        them fine), so the fast path must not copy them needlessly."""
        locked = tmp_path / "owner-locked.pdf"
        _encrypt(text_pdf, locked, owner="secret", user="")
        workspace = tmp_path / "ws"
        workspace.mkdir()

        assert prepare_pdf_for_conversion(locked, workspace) == locked

    def test_unreadable_for_fitz_is_repaired_via_pikepdf(
        self, text_pdf, tmp_path, monkeypatch
    ):
        """Files PyMuPDF cannot parse get a pikepdf structural rewrite."""
        import fitz

        def refuse(*_args, **_kwargs):
            raise RuntimeError("cannot open broken xref")

        monkeypatch.setattr(fitz, "open", refuse)
        workspace = tmp_path / "ws"
        workspace.mkdir()

        prepared = prepare_pdf_for_conversion(text_pdf, workspace)

        assert prepared != text_pdf
        assert prepared.parent == workspace
        assert prepared.stat().st_size > 0

    def test_user_password_pdf_raises_actionable_error(self, text_pdf, tmp_path):
        locked = tmp_path / "user-locked.pdf"
        _encrypt(text_pdf, locked, owner="secret", user="secret")
        workspace = tmp_path / "ws"
        workspace.mkdir()

        with pytest.raises(ProcessingError, match="password-protected"):
            prepare_pdf_for_conversion(
                locked, workspace, display_name="report.pdf"
            )

    def test_garbage_raises_damaged_error(self, tmp_path):
        garbage = tmp_path / "junk.pdf"
        garbage.write_bytes(b"%PDF-1.7 not really a pdf at all")
        workspace = tmp_path / "ws"
        workspace.mkdir()

        with pytest.raises(ProcessingError, match=r"damaged|not a valid"):
            prepare_pdf_for_conversion(garbage, workspace)


class TestPdfToDocx:
    def test_converts_clean_pdf(self, text_pdf, tmp_path):
        output = tmp_path / "out.docx"
        assert pdf_to_docx(text_pdf, output) == output
        assert output.stat().st_size > 0

    def test_owner_locked_pdf_converts_after_preflight(self, text_pdf, tmp_path):
        """The full task-side chain: normalize, then convert."""
        locked = tmp_path / "owner-locked.pdf"
        _encrypt(text_pdf, locked, owner="secret", user="")
        workspace = tmp_path / "ws"
        workspace.mkdir()

        prepared = prepare_pdf_for_conversion(locked, workspace)
        output = tmp_path / "out.docx"
        assert pdf_to_docx(prepared, output).stat().st_size > 0

    def test_fallback_extracts_text(self, text_pdf, tmp_path):
        from docx import Document

        output = tmp_path / "fallback.docx"
        _fallback_pdf_to_docx(text_pdf, output, first_page=None, last_page=None)

        text = "\n".join(p.text for p in Document(str(output)).paragraphs)
        assert "Hello page 1" in text
        assert "Hello page 2" in text

    def test_fallback_respects_page_range(self, text_pdf, tmp_path):
        from docx import Document

        output = tmp_path / "fallback-range.docx"
        _fallback_pdf_to_docx(text_pdf, output, first_page=2, last_page=2)

        text = "\n".join(p.text for p in Document(str(output)).paragraphs)
        assert "Hello page 1" not in text
        assert "Hello page 2" in text
