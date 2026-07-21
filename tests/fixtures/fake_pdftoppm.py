"""Stand-in for Poppler's ``pdftoppm`` used in tests.

Mimics the CLI surface the poppler util relies on: ``-jpeg``/``-png``,
``-r <dpi>``, optional ``-f``/``-l`` page range, then ``<input> <prefix>``.
Renders a fake 3-page document (honouring the page range) by writing
``<prefix>-<n>.<ext>`` files whose bytes embed the requested dpi/quality so
tests can assert options reached the binary.

Failure modes via input-content markers (inputs have UUID names):
``FAILMODE`` → exit 0 with no output; ``CRASHMODE`` → exit 9.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

TOTAL_PAGES = 3


def _real_image_bytes(fmt: str) -> bytes:
    """A genuine tiny image so downstream consumers (Pillow) can open it."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (120, 40, 40)).save(buffer, format=fmt)
    return buffer.getvalue()


def _flag_value(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv else None


def main(argv: list[str]) -> int:
    input_path = Path(argv[-2])
    prefix = Path(argv[-1])

    content = input_path.read_bytes()
    if b"CRASHMODE" in content:
        sys.stderr.write("Syntax Error: simulated poppler crash\n")
        return 9
    if b"FAILMODE" in content:
        return 0

    if "-png" in argv:
        extension, image = "png", _real_image_bytes("PNG")
    else:
        extension, image = "jpg", _real_image_bytes("JPEG")
    dpi = _flag_value(argv, "-r") or "150"
    quality = _flag_value(argv, "-jpegopt") or ""
    if "-gray" in argv:
        quality += " gray"
    first = int(_flag_value(argv, "-f") or 1)
    # An explicit -l is honoured fully (parallel chunk rendering relies on
    # exact ranges); without it, pretend the document has TOTAL_PAGES pages.
    explicit_last = _flag_value(argv, "-l")
    last = int(explicit_last) if explicit_last else TOTAL_PAGES

    prefix.parent.mkdir(parents=True, exist_ok=True)
    for page in range(first, last + 1):
        # Trailing marker bytes after the image data: readers ignore them,
        # tests assert on them to prove options reached the binary.
        (prefix.parent / f"{prefix.name}-{page}.{extension}").write_bytes(
            image + f" page={page} dpi={dpi} {quality}".encode()
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
