"""Stand-in for the ``unoconvert`` client used in tests.

Mimics the CLI surface the office pool relies on: positional ``INPUT OUTPUT``
as the last two arguments, plus ``--host``/``--port``/``--convert-to`` and
optional filter flags. Writes a fake PDF to OUTPUT, embedding its own argv so
tests can assert what was passed.

Failure modes are triggered by markers in the input file's content (same
convention as ``fake_soffice``): ``CRASHMODE`` exits 77; ``FAILMODE`` exits 0
without producing output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    input_path = Path(argv[-2])
    output_path = Path(argv[-1])

    content = input_path.read_bytes()
    if b"CRASHMODE" in content or b"UNOCRASH" in content:
        # UNOCRASH is unoconvert-specific: fake_soffice converts it fine,
        # letting tests assert the pool → soffice fallback end-to-end.
        sys.stderr.write("simulated converter crash\n")
        return 77
    if b"FAILMODE" in content:
        return 0  # exit 0, no output — the silent-failure mode

    output_path.write_bytes(
        b"%PDF-1.4\n% fake unoconvert\n% argv: "
        + json.dumps(argv).encode()
        + b"\n%%EOF\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
