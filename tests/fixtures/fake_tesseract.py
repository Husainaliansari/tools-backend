"""Stand-in for Tesseract used in tests (language auto-detection only).

Two CLI shapes are emulated:

* OSD:  ``tesseract <img> stdout --psm 0`` -> script/orientation report
* Text: ``tesseract <img> stdout -l eng --psm 3`` -> plain OCR text

Behaviour is steered through environment variables so tests can simulate
documents in any script/language without real image recognition:

* ``FAKE_TESSERACT_SCRIPT``  (default ``Latin``)
* ``FAKE_TESSERACT_TEXT``    (default an English sentence)
* ``FAKE_TESSERACT_FAIL=1``  -> exit 1 (e.g. "Too few characters")
"""

from __future__ import annotations

import os
import sys

_DEFAULT_TEXT = (
    "This is the scanned page and it was written in English so that "
    "the detector picks the English language from this text."
)


def main(argv: list[str]) -> int:
    if os.environ.get("FAKE_TESSERACT_FAIL") == "1":
        sys.stderr.write("Too few characters. Skipping this page\n")
        return 1

    if "--psm" in argv and argv[argv.index("--psm") + 1] == "0":
        script = os.environ.get("FAKE_TESSERACT_SCRIPT", "Latin")
        sys.stdout.write(
            "Page number: 0\n"
            "Orientation in degrees: 0\n"
            "Rotate: 0\n"
            "Orientation confidence: 12.34\n"
            f"Script: {script}\n"
            "Script confidence: 4.00\n"
        )
        return 0

    sys.stdout.write(os.environ.get("FAKE_TESSERACT_TEXT", _DEFAULT_TEXT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
