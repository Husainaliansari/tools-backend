"""Content hashing helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of a file, streamed in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
