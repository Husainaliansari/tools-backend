"""OCRmyPDF plugin: OpenCV-based deskew estimation.

OCRmyPDF asks Tesseract (``--psm 2``) for each page's skew angle, but
Tesseract 5 routinely answers ``0.0`` — or "Empty page!!" — for sparse or
low-contrast scans, so ``--deskew`` silently does nothing. This plugin
keeps the Tesseract OCR engine but replaces the angle estimator with a
projection-profile search: text lines are horizontal at the rotation whose
row-projection variance is highest.

Loaded per invocation via ``ocrmypdf --plugin <path to this file>``; the
subprocess runs inside the backend venv, so cv2/numpy are importable.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from ocrmypdf import hookimpl
from ocrmypdf.builtin_plugins.tesseract_ocr import TesseractOcrEngine

#: Beyond ~10 degrees a scan is "rotated", not "skewed" — that is
#: --rotate-pages territory, and correcting it here would crop corners.
MAX_SKEW_DEGREES = 10.0

#: Analysis resolution; higher buys little accuracy and costs quadratic time.
_TARGET_LONG_SIDE = 1100

#: Ink-coverage ratios outside this window mean a blank page or a photo,
#: where a projection profile has no meaningful peak.
_INK_RANGE = (0.001, 0.40)


def _projection_score(binary: np.ndarray, angle: float) -> float:
    height, width = binary.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    rotated = cv2.warpAffine(binary, matrix, (width, height), flags=cv2.INTER_NEAREST)
    projection = rotated.sum(axis=1, dtype=np.float64)
    return float(np.var(projection))


def estimate_skew_degrees(image_path: Path) -> float:
    """Counter-clockwise rotation (PIL convention) that straightens the
    page, or 0.0 when the page is already straight or unmeasurable."""
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return 0.0
    height, width = image.shape
    scale = _TARGET_LONG_SIDE / max(height, width)
    if scale < 1.0:
        image = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    binary = cv2.threshold(image, 0, 1, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    ink = float(binary.mean())
    if not _INK_RANGE[0] <= ink <= _INK_RANGE[1]:
        return 0.0

    def best(candidates: np.ndarray) -> float:
        return float(max(candidates, key=lambda a: _projection_score(binary, a)))

    coarse = best(np.arange(-MAX_SKEW_DEGREES, MAX_SKEW_DEGREES + 0.5, 0.5))
    fine = best(np.arange(coarse - 0.5, coarse + 0.55, 0.1))
    if abs(fine) < 0.2:
        return 0.0  # measurement noise, not skew
    # Demand a clear win over "leave it alone" so straight pages stay put.
    if _projection_score(binary, fine) < 1.05 * _projection_score(binary, 0.0):
        return 0.0
    return fine


class CvDeskewTesseractEngine(TesseractOcrEngine):
    """Tesseract engine with the deskew estimator swapped for OpenCV."""

    @staticmethod
    def get_deskew(input_file, options) -> float:
        return estimate_skew_degrees(Path(input_file))


@hookimpl
def get_ocr_engine(options):
    return CvDeskewTesseractEngine()
