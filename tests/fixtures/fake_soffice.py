"""Stand-in for ``soffice --headless --convert-to pdf`` used in tests.

Mimics the CLI surface the office util relies on: reads ``--outdir`` and the
trailing input path, writes ``<stem>.pdf`` into the outdir, exits 0.

Failure modes are triggered by markers in the input file's *content* (inputs
arrive under generated UUID names, so filenames cannot be used): a file
containing ``FAILMODE`` exits 0 without producing output (LibreOffice's
silent-failure mode); ``CRASHMODE`` exits 77.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    outdir = Path(argv[argv.index("--outdir") + 1])
    input_path = Path(argv[-1])

    content = input_path.read_bytes()
    if b"CRASHMODE" in content:
        sys.stderr.write("simulated converter crash\n")
        return 77
    if b"FAILMODE" in content:
        return 0  # exit 0, no output — LibreOffice's silent failure

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{input_path.stem}.pdf").write_bytes(
        b"%PDF-1.4\n% converted from " + input_path.name.encode() + b"\n%%EOF\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
