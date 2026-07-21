"""OCR and structural repair of PDFs (OCRmyPDF, QPDF)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from app.config import get_settings
from app.exceptions.jobs import ProcessingError
from app.utils.command import CommandError, run_tool_command, split_launcher
from app.utils.ocr_language import ocr_subprocess_env

# OCRmyPDF documented exit codes -> user-actionable messages. Codes not
# listed here fall through to the generic converter-failure handling.
_OCR_EXIT_MESSAGES = {
    2: "'{name}' does not appear to be a valid PDF, or it is damaged. "
    "Try the Repair PDF tool first.",
    6: "'{name}' already contains selectable text on every page. "
    "Enable 'Force OCR' to re-recognise it anyway.",
    8: "'{name}' is password-protected. Unlock it first, then run OCR.",
}


def _ocrmypdf_launcher() -> list[str]:
    """Argv prefix for OCRmyPDF. The default bare name degrades to
    ``python -m ocrmypdf`` in this interpreter's environment, where the
    package is installed as a dependency."""
    settings = get_settings()
    launcher = split_launcher(settings.OCRMYPDF_BIN)
    if launcher == ["ocrmypdf"] and not shutil.which("ocrmypdf"):
        return [sys.executable, "-m", "ocrmypdf"]
    return launcher


def ocr_pdf(
    input_path: Path,
    output_path: Path,
    *,
    language: str = "eng",
    deskew: bool = False,
    rotate_pages: bool = True,
    force_ocr: bool = False,
    timeout: int | None = None,
) -> Path:
    """Add a searchable text layer via OCRmyPDF (Tesseract underneath).

    The original pages are preserved; recognised text is overlaid as an
    invisible, selectable layer. ``--output-type pdf`` skips the PDF/A
    conversion step — faster, and keeps the source colour spaces intact.
    """
    command = [
        *_ocrmypdf_launcher(),
        "-l",
        language,
        "--output-type",
        "pdf",
    ]
    # --skip-text leaves born-digital pages alone; --force-ocr rasterises all.
    command.append("--force-ocr" if force_ocr else "--skip-text")
    if rotate_pages:
        # Auto-correct pages scanned sideways/upside-down (Tesseract OSD).
        # OSD reports 'Rotate: 0' for upright pages even at low confidence,
        # so a near-zero threshold fixes sparse rotated pages without
        # flipping correct ones (the default 14 skips most real scans).
        command += ["--rotate-pages", "--rotate-pages-threshold", "2"]
    if deskew:
        # Tesseract's own skew estimator reports 0.0 for many real scans;
        # the plugin swaps in an OpenCV projection-profile estimator.
        plugin = Path(__file__).with_name("ocrmypdf_deskew_plugin.py")
        command += ["--deskew", "--plugin", str(plugin)]
    command += [str(input_path), str(output_path)]

    try:
        run_tool_command(
            command,
            tool_label="OCR engine",
            timeout=timeout,
            env=ocr_subprocess_env(),
        )
    except CommandError as exc:
        message = _OCR_EXIT_MESSAGES.get(exc.returncode or 0)
        if message:
            raise ProcessingError(message.format(name=input_path.name)) from exc
        raise

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ProcessingError(f"OCR produced no output for '{input_path.name}'.")
    return output_path


def repair_pdf(
    input_path: Path, output_path: Path, *, timeout: int | None = None
) -> Path:
    """Rebuild a PDF's structure with libqpdf, via the in-process pikepdf
    binding (recovers broken cross-reference tables, appended/leading junk
    bytes, mismatched object offsets and similar structural damage).

    libqpdf is the same engine the ``qpdf`` command-line tool uses, but it
    ships inside the pikepdf wheel, so repair works uniformly across dev and
    production without depending on an external binary being installed and on
    PATH. ``attempt_recovery`` (opening) makes libqpdf reconstruct a damaged
    xref by scanning the file for objects; the save then writes a fresh,
    well-formed structure. Page content, fonts and images are carried over
    verbatim — this is a structural rewrite, not a re-render, so the original
    document content and formatting are preserved.

    ``timeout`` is accepted for signature parity with :func:`ocr_pdf`; the
    rewrite is a bounded in-process operation with nothing to time out.
    """
    import pikepdf

    name = input_path.name
    too_damaged = ProcessingError(
        f"'{name}' is too damaged to repair, or is not a valid PDF file."
    )
    try:
        with pikepdf.open(input_path, attempt_recovery=True) as pdf:
            if len(pdf.pages) == 0:
                raise ProcessingError(f"'{name}' contains no recoverable pages.")
            # A full rewrite: object_stream_mode=generate rebuilds compact,
            # valid object streams; fix_metadata_version repairs a stale
            # XMP/version mismatch. Existing (owner) encryption is preserved.
            pdf.save(
                output_path,
                fix_metadata_version=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
            )
    except pikepdf.PasswordError as exc:
        raise ProcessingError(
            f"'{name}' is password-protected. Use the Unlock PDF tool to "
            "remove the password, then run Repair."
        ) from exc
    except ProcessingError:
        raise
    except Exception as exc:
        # libqpdf exhausted recovery (no trailer/root, not a PDF), or the
        # save hit unrecoverable objects. Any failure here means the file
        # cannot be repaired — surface one clear, non-technical message
        # rather than leaking a raw internal error to the user.
        raise too_damaged from exc

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ProcessingError(f"Repair produced no output for '{name}'.")

    # Critical: libqpdf can open a badly-truncated file in recovery mode and
    # still write a structurally-broken output *without* raising — the saved
    # file then fails to open in any viewer. Re-open the result strictly (no
    # recovery): a genuinely repaired PDF must parse cleanly with readable
    # pages. If it does not, the repair did not succeed, so we must not hand
    # back a "repaired" file that is still broken.
    try:
        with pikepdf.open(output_path, attempt_recovery=False) as repaired:
            if len(repaired.pages) == 0:
                raise ProcessingError(f"'{name}' contains no recoverable pages.")
    except ProcessingError:
        output_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise ProcessingError(
            f"'{name}' is too damaged to repair — the recoverable data does "
            "not form a valid PDF."
        ) from exc

    return output_path
