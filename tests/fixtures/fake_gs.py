"""Stand-in for Ghostscript's pdfwrite compression used in tests.

Reads ``-sOutputFile=<path>`` and the trailing input path; writes a valid
(smaller) PDF produced with pypdf so downstream consumers can open it. The
``-dPDFSETTINGS`` preset is embedded as PDF metadata so tests can assert the
quality option reached the binary.

Failure modes via input-content markers: ``CRASHMODE`` → exit 1.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def main(argv: list[str]) -> int:
    output_path = None
    preset = "unset"
    for arg in argv:
        if arg.startswith("-sOutputFile="):
            output_path = Path(arg.split("=", 1)[1])
        elif arg.startswith("-dPDFSETTINGS="):
            preset = arg.split("=", 1)[1]
    input_path = Path(argv[-1])

    content = input_path.read_bytes()
    if b"CRASHMODE" in content:
        sys.stderr.write("simulated ghostscript failure\n")
        return 1

    reader = PdfReader(io.BytesIO(content))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({"/GSPreset": preset})
    assert output_path is not None
    with output_path.open("wb") as handle:
        writer.write(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
