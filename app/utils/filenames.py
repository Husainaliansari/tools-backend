"""Filename helpers.

Client-supplied filenames are untrusted input: they can contain path
separators, control characters, reserved device names (Windows) or be
arbitrarily long. Files are *stored* under generated UUID names — the original
name is only kept for display and for the Content-Disposition header — but we
still sanitise it defensively before persisting or echoing it back.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from pathlib import PurePosixPath, PureWindowsPath

# Characters invalid on Windows plus control chars; conservative superset.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_FILENAME_LENGTH = 200


def sanitize_filename(name: str, *, fallback: str = "file") -> str:
    """Return a display-safe version of a client-supplied filename.

    Strips any directory components, normalises unicode, removes unsafe
    characters and caps the length while preserving the extension.
    """
    # Drop directory components regardless of the client's OS conventions.
    name = PureWindowsPath(PurePosixPath(name).name).name
    name = unicodedata.normalize("NFKC", name)
    name = _UNSAFE_CHARS.sub("_", name).strip(" .")

    if not name:
        return fallback

    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"{stem}_"

    if suffix:
        # Keep the extension; trim the stem to respect the total cap.
        max_stem = MAX_FILENAME_LENGTH - len(suffix) - 1
        return f"{stem[:max_stem] or fallback}.{suffix}"
    return stem[:MAX_FILENAME_LENGTH] or fallback


def file_extension(name: str) -> str:
    """Lower-cased extension without the dot ('' if none)."""
    suffix = PureWindowsPath(PurePosixPath(name).name).suffix
    return suffix.lstrip(".").lower()


def file_stem(name: str) -> str:
    """Filename without directories or extension ('Q3 Report.pdf' → 'Q3 Report')."""
    return PurePosixPath(name).stem


#: Raster image types accepted as secondary inputs (watermark/signature stamps).
IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png"})


def generate_stored_name(extension: str) -> str:
    """Collision-free on-disk name; never derived from client input."""
    ext = extension.lstrip(".").lower()
    return f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex


def human_readable_size(size_bytes: int) -> str:
    """Format a byte count for humans (e.g. '2.4 MB')."""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"  # pragma: no cover - unreachable
