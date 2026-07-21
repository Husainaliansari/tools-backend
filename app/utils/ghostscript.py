"""Ghostscript-based PDF compression.

Ghostscript's ``pdfwrite`` device with a ``/PDFSETTINGS`` preset is the
industry-standard lossy PDF optimiser: it downsamples images, re-encodes
streams and drops duplicate resources. Quality presets map to Ghostscript's
built-ins (screen < ebook < printer < prepress).
"""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.exceptions.jobs import ProcessingError
from app.utils.command import run_tool_command, split_launcher

#: User-facing quality levels → Ghostscript presets.
QUALITY_PRESETS = {
    "extreme": "/screen",  # 72 dpi images — smallest files
    "recommended": "/ebook",  # 150 dpi — good screen quality
    "less": "/printer",  # 300 dpi — light compression
}


def compress_pdf(
    input_path: Path,
    output_path: Path,
    *,
    quality: str = "recommended",
    timeout: int | None = None,
) -> Path:
    """Compress one PDF; returns ``output_path``."""
    preset = QUALITY_PRESETS.get(quality)
    if preset is None:
        raise ProcessingError(f"Unknown compression quality '{quality}'.")

    settings = get_settings()
    command = [
        *split_launcher(settings.GHOSTSCRIPT_BIN),
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.5",
        f"-dPDFSETTINGS={preset}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        "-dSAFER",
        f"-sOutputFile={output_path}",
        str(input_path),
    ]
    run_tool_command(command, tool_label="PDF compressor", timeout=timeout)

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ProcessingError(
            f"Compression produced no output for '{input_path.name}'."
        )
    return output_path
