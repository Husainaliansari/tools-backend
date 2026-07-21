"""PDF → Word conversion (pdf2docx + pikepdf pre-flight).

pdf2docx reconstructs editable DOCX from PDF layout analysis (tables,
paragraphs, images) — substantially better output than LibreOffice's PDF
import for text documents. The import is deferred: the library (PyMuPDF
backed) is heavy and only workers need it.

Reliability comes from bracketing pdf2docx with two safety nets:

* :func:`prepare_pdf_for_conversion` — pdf2docx refuses any encrypted PDF
  (even owner-password files every viewer opens) and trips over mildly
  corrupt xref tables. Such files are routed through pikepdf, which repairs
  structure and strips empty-password encryption; only a real user password
  is surfaced as an error.
* a PyMuPDF fallback — when pdf2docx's layout parser crashes on an exotic
  page, the file is re-converted text-block-by-text-block (page images for
  pages without text) instead of failing the job.

Conversion is CPU-bound pure Python, so threads win nothing (GIL); the
speed-ups here are process-based and used only where child processes can be
spawned (see :func:`can_spawn_processes`):

* several inputs — the caller converts files concurrently in a process pool;
* one large input — pdf2docx's own ``multi_processing`` splits pages across
  processes (:func:`page_parallel_workers` decides when it pays off).
"""

from __future__ import annotations

import io
import logging
import multiprocessing
import os
from pathlib import Path

from app.exceptions.jobs import ProcessingError
from app.logging import get_logger

logger = get_logger(__name__)

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

#: Below this page count the per-process spawn/import overhead outweighs the
#: parallel parsing gain, so the conversion stays single-process.
_MIN_PAGES_FOR_PARALLEL = 8

#: Upper bound on worker processes — pdf2docx workers are memory-hungry and
#: page-splitting shows diminishing returns beyond this.
MAX_CONVERT_WORKERS = 4


def can_spawn_processes() -> bool:
    """Whether this process may create child processes.

    Daemonic processes (e.g. Celery prefork workers) cannot — parallel
    conversion silently degrades to single-process there.
    """
    try:
        return not multiprocessing.current_process().daemon
    except Exception:  # pragma: no cover - defensive
        return False


def page_parallel_workers(input_path: Path) -> int:
    """Workers for pdf2docx page-level multi-processing (0 = stay serial)."""
    if not can_spawn_processes():
        return 0
    try:
        import fitz

        with fitz.open(str(input_path)) as doc:
            pages = doc.page_count
    except Exception:
        return 0  # unreadable here — let the converter surface the real error
    if pages < _MIN_PAGES_FOR_PARALLEL:
        return 0
    return max(2, min(MAX_CONVERT_WORKERS, os.cpu_count() or 1))


def prepare_pdf_for_conversion(
    input_path: Path,
    workspace: Path,
    *,
    display_name: str | None = None,
) -> Path:
    """Return a PDF path pdf2docx can safely consume.

    Fast path (the overwhelming majority): a cleanly readable, unencrypted
    file is returned untouched. Encrypted files (pdf2docx rejects them all,
    including owner-password documents that open fine in any viewer) and
    files PyMuPDF cannot parse are rewritten through pikepdf, which repairs
    xref/structure damage and drops empty-password encryption. Only a PDF
    needing a real password is a hard error — with an actionable message.
    """
    name = display_name or input_path.name
    needs_normalize = False
    try:
        import fitz

        with fitz.open(str(input_path)) as doc:
            if doc.needs_pass and not doc.authenticate(""):
                raise ProcessingError(
                    f"'{name}' is password-protected. Use the Unlock PDF tool "
                    "to remove the password, then convert it."
                )
            needs_normalize = bool(doc.is_encrypted or doc.needs_pass)
            if not needs_normalize and doc.page_count == 0:
                raise ProcessingError(f"'{name}' contains no pages.")
    except ProcessingError:
        raise
    except Exception:
        # Unreadable for PyMuPDF — let pikepdf try a structural repair.
        needs_normalize = True

    if not needs_normalize:
        return input_path

    try:
        import pikepdf
    except ImportError:  # pragma: no cover - deployment problem
        return input_path  # degrade to the old behaviour rather than block

    normalized = workspace / f"{input_path.stem}-normalized.pdf"
    try:
        with pikepdf.open(input_path) as pdf:
            pdf.save(normalized)
    except pikepdf.PasswordError as exc:
        raise ProcessingError(
            f"'{name}' is password-protected. Use the Unlock PDF tool to "
            "remove the password, then convert it."
        ) from exc
    except Exception as exc:
        raise ProcessingError(
            f"'{name}' could not be read — the file appears to be damaged "
            "or is not a valid PDF."
        ) from exc
    logger.info("pdf_normalized_for_conversion", input=name)
    return normalized


def _fallback_pdf_to_docx(
    input_path: Path,
    output_path: Path,
    *,
    first_page: int | None,
    last_page: int | None,
) -> None:
    """Last-resort PDF→DOCX via PyMuPDF text extraction.

    Produces paragraphs from each page's text blocks and embeds a page
    render for pages with no extractable text (scans). Loses complex layout
    — acceptable only because the alternative is failing the file outright.
    """
    import fitz
    from docx import Document
    from docx.shared import Inches

    document = Document()
    with fitz.open(str(input_path)) as pdf:
        start = (first_page - 1) if first_page else 0
        stop = min(last_page or pdf.page_count, pdf.page_count)
        for number in range(start, stop):
            page = pdf[number]
            wrote_text = False
            for block in page.get_text("blocks", sort=True):
                content = block[4].strip()
                if content and block[6] == 0:  # text blocks only, not images
                    document.add_paragraph(content)
                    wrote_text = True
            if not wrote_text:
                pixmap = page.get_pixmap(dpi=150)
                document.add_picture(
                    io.BytesIO(pixmap.tobytes("png")),
                    width=Inches(min(6.5, pixmap.width / 150)),
                )
            if number + 1 < stop:
                document.add_page_break()
    document.save(str(output_path))


def pdf_to_docx(
    input_path: Path,
    output_path: Path,
    *,
    first_page: int | None = None,
    last_page: int | None = None,
    page_workers: int = 0,
    display_name: str | None = None,
) -> Path:
    """Convert one PDF to DOCX; returns ``output_path``.

    ``page_workers`` > 1 enables pdf2docx's page-level multi-processing —
    only pass it when :func:`page_parallel_workers` says it is worthwhile.
    ``display_name`` is the user-facing name for error messages (on-disk
    names are storage UUIDs the user has never seen).
    """
    try:
        from pdf2docx import Converter
    except ImportError as exc:  # pragma: no cover - deployment problem
        raise ProcessingError(
            "The PDF-to-Word converter is not installed on this server."
        ) from exc

    name = display_name or input_path.name

    # pdf2docx logs noisily at INFO; keep worker logs clean.
    logging.getLogger("pdf2docx").setLevel(logging.WARNING)

    parallel_kwargs = (
        {"multi_processing": True, "cpu_count": page_workers}
        if page_workers > 1
        else {}
    )

    try:
        converter = Converter(str(input_path))
    except Exception as exc:
        raise ProcessingError(
            f"'{name}' could not be opened as a PDF — the file appears to be "
            "damaged."
        ) from exc
    try:
        converter.convert(
            str(output_path),
            start=(first_page - 1) if first_page else 0,
            end=last_page,  # None = to the end; pdf2docx end is exclusive-ish
            **parallel_kwargs,
        )
    except Exception as exc:
        # Layout analysis gave up on some page. Degrade to the simple
        # extractor rather than failing a file every PDF viewer can read.
        logger.warning(
            "pdf2docx_failed_using_fallback", input=name, error=str(exc)
        )
        try:
            _fallback_pdf_to_docx(
                input_path, output_path, first_page=first_page, last_page=last_page
            )
        except Exception:
            raise ProcessingError(
                f"Could not convert '{name}' to Word. The file may be damaged "
                f"or use unsupported features. (Converter said: {exc})"
            ) from exc
    finally:
        converter.close()

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ProcessingError(
            f"Converting '{name}' produced an empty document."
        )
    return output_path
