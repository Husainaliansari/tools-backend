"""Stand-in for OCRmyPDF used in tests.

CLI shape: ``ocrmypdf -l <lang> [--skip-text|--force-ocr] [--deskew] in out``.
Writes a valid PDF (pypdf rewrite of the input) whose metadata records the
flags it received, so tests can assert options reached the binary.

``CRASHMODE`` in the input content → exit 6 (ocrmypdf's "prior OCR text
found" exit code, mapped by the app to a user-facing message).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def main(argv: list[str]) -> int:
    input_path, output_path = Path(argv[-2]), Path(argv[-1])
    content = input_path.read_bytes()
    if b"CRASHMODE" in content:
        sys.stderr.write("simulated ocr failure\n")
        return 6

    language = argv[argv.index("-l") + 1] if "-l" in argv else ""
    flags = " ".join(a for a in argv if a.startswith("--"))

    reader = PdfReader(io.BytesIO(content))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({"/OCRLang": language, "/OCRFlags": flags})
    with output_path.open("wb") as handle:
        writer.write(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
