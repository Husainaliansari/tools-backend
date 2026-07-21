"""Unit tests for redact_text — layout preservation and combined redaction.

These use PyMuPDF directly to inspect page internals (vector drawings, text)
that pypdf cannot easily expose.
"""

from __future__ import annotations

import pytest

from app.exceptions.jobs import ProcessingError
from app.utils.pdf_document import redact_text

fitz = pytest.importorskip("fitz")


def _text_of(path) -> str:
    doc = fitz.open(str(path))
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _drawing_count(path) -> int:
    doc = fitz.open(str(path))
    try:
        return len(doc[0].get_drawings())
    finally:
        doc.close()


def test_preserves_vector_line_when_redacted_word_overlaps_it(tmp_path):
    """A redacted word sitting on a table rule must not delete the rule."""
    source = tmp_path / "table.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.draw_line(fitz.Point(40, 200), fitz.Point(360, 200), color=(0, 0, 0), width=1)
    page.insert_text(fitz.Point(50, 197), "SECRET on the line", fontsize=11)
    doc.save(str(source))
    doc.close()

    before = _drawing_count(source)
    out = tmp_path / "out.pdf"
    regions = redact_text(source, out, texts=["SECRET"])

    assert regions >= 1
    assert "SECRET" not in _text_of(out)
    # The rule survives (the added black box only increases the drawing count).
    assert _drawing_count(out) >= before


def test_text_and_area_combined(tmp_path):
    source = tmp_path / "mix.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text(fitz.Point(50, 100), "Confidential name here", fontsize=12)
    doc.save(str(source))
    doc.close()

    out = tmp_path / "out.pdf"
    regions = redact_text(
        source,
        out,
        texts=["Confidential"],
        areas=[{"page": 1, "x0": 40, "y0": 150, "x1": 300, "y1": 200}],
    )
    assert regions >= 2
    assert "Confidential" not in _text_of(out)


def test_clips_area_to_page_bounds(tmp_path):
    """An area extending past the page is clipped, not rejected."""
    source = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(str(source))
    doc.close()

    out = tmp_path / "out.pdf"
    regions = redact_text(
        source, out, areas=[{"page": 1, "x0": 50, "y0": 50, "x1": 9999, "y1": 9999}]
    )
    assert regions == 1


def test_missing_term_raises_naming_it(tmp_path):
    source = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(72, 72), "present", fontsize=12)
    doc.save(str(source))
    doc.close()

    out = tmp_path / "out.pdf"
    with pytest.raises(ProcessingError) as exc:
        redact_text(source, out, texts=["present", "absent-xyz"])
    assert "absent-xyz" in str(exc.value)
    assert not out.exists()  # nothing written when redaction is aborted


@pytest.mark.parametrize("mode", ["black", "white", "color", "blur", "pixelate"])
def test_area_modes_all_remove_content(tmp_path, mode):
    """Every visual style removes the underlying text, not just covers it."""
    source = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text(fitz.Point(50, 100), "TOP-SECRET-DATA", fontsize=14)
    doc.save(str(source))
    doc.close()

    out = tmp_path / "out.pdf"
    regions = redact_text(
        source,
        out,
        areas=[
            {
                "page": 1,
                "x0": 40,
                "y0": 80,
                "x1": 300,
                "y1": 110,
                "mode": mode,
                "color": "#ff0000",
                "opacity": 0.6,
            }
        ],
    )
    assert regions == 1
    assert "TOP-SECRET-DATA" not in _text_of(out)


def test_blur_and_pixelate_embed_a_raster(tmp_path):
    """Blur/pixelate leave exactly one image (the obscured snapshot) behind."""
    source = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text(fitz.Point(50, 100), "hide me", fontsize=14)
    doc.save(str(source))
    doc.close()

    out = tmp_path / "out.pdf"
    redact_text(
        source,
        out,
        areas=[{"page": 1, "x0": 40, "y0": 80, "x1": 200, "y1": 110, "mode": "blur"}],
    )
    result = fitz.open(str(out))
    try:
        assert len(result[0].get_images(full=True)) == 1
        assert "hide me" not in result[0].get_text()
    finally:
        result.close()


def test_unknown_area_mode_rejected(tmp_path):
    source = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(source))
    doc.close()

    with pytest.raises(ProcessingError) as exc:
        redact_text(
            source,
            tmp_path / "out.pdf",
            areas=[{"page": 1, "x0": 0, "y0": 0, "x1": 10, "y1": 10, "mode": "nope"}],
        )
    assert "mode" in str(exc.value)


def test_no_terms_no_areas_rejected(tmp_path):
    source = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(source))
    doc.close()

    with pytest.raises(ProcessingError):
        redact_text(source, tmp_path / "out.pdf", texts=[], areas=[])
