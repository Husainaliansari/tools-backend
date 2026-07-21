"""Enhance worker tasks: OCR, repair, compress-scanned."""

from __future__ import annotations

from app.tasks.base import (
    ProducedFile,
    ToolRunContext,
    process_each_input,
    run_tool_job,
)
from app.utils.filenames import file_stem
from app.utils.ghostscript import compress_pdf
from app.utils.ocr_language import detect_document_language
from app.utils.pdf_enhance import ocr_pdf, repair_pdf
from app.workers.celery_app import celery_app


@celery_app.task(name="tools.ocr", bind=True)
def ocr(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        options = ctx.options

        def operate(path, name, index):
            language = options.get("language", "eng")
            if options.get("auto_detect_language", True):
                # Best-effort: falls back to the selected/default language.
                language = detect_document_language(
                    path, ctx.workspace, fallback=language
                ).language
            output = ocr_pdf(
                path,
                ctx.workspace / f"out-{index}.pdf",
                language=language,
                deskew=options.get("deskew", False),
                rotate_pages=options.get("rotate_pages", True),
                force_ocr=options.get("force_ocr", False),
            )
            return ProducedFile(output, f"{file_stem(name)}-ocr.pdf")

        return process_each_input(ctx, operate)

    run_tool_job(job_id, process)


@celery_app.task(name="tools.repair", bind=True)
def repair(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        def operate(path, name, index):
            output = repair_pdf(path, ctx.workspace / f"out-{index}.pdf")
            return ProducedFile(output, f"{file_stem(name)}-repaired.pdf")

        return process_each_input(ctx, operate)

    run_tool_job(job_id, process)


@celery_app.task(name="tools.compress-scanned", bind=True)
def compress_scanned(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        quality = ctx.options.get("quality", "extreme")

        def operate(path, name, index):
            output = compress_pdf(
                path, ctx.workspace / f"out-{index}.pdf", quality=quality
            )
            return ProducedFile(output, f"{file_stem(name)}-compressed.pdf")

        return process_each_input(ctx, operate)

    run_tool_job(job_id, process)
