"""Unit tests for the OpenCV skew estimator used by the OCRmyPDF plugin."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from app.utils.ocrmypdf_deskew_plugin import estimate_skew_degrees

TEXT = [
    "The quick brown fox jumps over the lazy dog.",
    "Invoice number 42 was paid in full today.",
    "Please contact support for more details.",
    "This paragraph exists to give the estimator",
    "several long horizontal text lines to measure.",
]


def _page(skew: float, tmp_path):
    img = Image.new("L", (1200, 1600), 255)
    draw = ImageDraw.Draw(img)
    for row, line in enumerate(TEXT * 3):
        draw.text((100, 150 + row * 90), line, fill=0)
    if skew:
        img = img.rotate(skew, expand=True, fillcolor=255)
    path = tmp_path / f"page-{skew}.png"
    img.save(path)
    return path


@pytest.mark.parametrize("skew", [3.0, -4.5, 8.0])
def test_detects_skew_within_tolerance(skew, tmp_path):
    estimate = estimate_skew_degrees(_page(skew, tmp_path))
    # Correction is the opposite rotation, within half a degree.
    assert estimate == pytest.approx(-skew, abs=0.5)


def test_straight_page_untouched(tmp_path):
    assert estimate_skew_degrees(_page(0.0, tmp_path)) == 0.0


def test_blank_page_untouched(tmp_path):
    path = tmp_path / "blank.png"
    Image.new("L", (1200, 1600), 255).save(path)
    assert estimate_skew_degrees(path) == 0.0
