"""Office conversion worker tasks: Word/Excel → PDF and PDF → Word."""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed

from app.tasks.base import (
    ProducedFile,
    ToolRunContext,
    process_each_input,
    process_each_input_parallel,
    run_tool_job,
)
from app.utils.filenames import file_stem
from app.utils.office import libreoffice_convert, office_conversion_slots
from app.utils.pdf_convert import (
    DOCX_MEDIA_TYPE,
    MAX_CONVERT_WORKERS,
    can_spawn_processes,
    page_parallel_workers,
    pdf_to_docx,
    prepare_pdf_for_conversion,
)
from app.workers.celery_app import celery_app


def _office_to_pdf(ctx: ToolRunContext, export_filter: str) -> list[ProducedFile]:
    filter_options = {"SelectPdfVersion": 2} if ctx.options.get("pdf_a") else None

    def operate(path, name, index):
        output = libreoffice_convert(
            path,
            ctx.workspace,
            filter_name=export_filter if filter_options else None,
            filter_options=filter_options,
            display_name=name,
        )
        return ProducedFile(output, f"{file_stem(name)}.pdf")

    # Documents convert independently — one per available conversion slot.
    return process_each_input_parallel(
        ctx, operate, max_workers=office_conversion_slots()
    )


@celery_app.task(name="tools.word-to-pdf", bind=True)
def word_to_pdf(self, job_id: str) -> None:
    run_tool_job(job_id, lambda ctx: _office_to_pdf(ctx, "writer_pdf_Export"))


@celery_app.task(name="tools.excel-to-pdf", bind=True)
def excel_to_pdf(self, job_id: str) -> None:
    run_tool_job(job_id, lambda ctx: _office_to_pdf(ctx, "calc_pdf_Export"))


def _pdf_to_word_parallel(ctx: ToolRunContext) -> list[ProducedFile]:
    """Convert the inputs concurrently, one child process per file.

    pdf2docx is CPU-bound pure Python, so a process pool turns a multi-file
    job's wall time from the *sum* of the per-file times into roughly the
    *slowest* file. Progress advances as each file lands.
    """
    options = ctx.options
    items = list(zip(ctx.input_paths, ctx.input_names, strict=True))
    outputs = [ctx.workspace / f"converted-{i}.docx" for i in range(len(items))]
    workers = min(len(items), max(1, (os.cpu_count() or 2) - 1), MAX_CONVERT_WORKERS)

    # Pre-flight in the parent (cheap): repaired/decrypted copies where
    # needed, and clear errors for password-protected files before any
    # worker process spins up.
    prepared = [
        prepare_pdf_for_conversion(path, ctx.workspace, display_name=name)
        for path, name in items
    ]

    produced: list[ProducedFile | None] = [None] * len(items)
    completed = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                pdf_to_docx,
                prepared[index],
                outputs[index],
                first_page=options.get("first_page"),
                last_page=options.get("last_page"),
                display_name=items[index][1],
            ): index
            for index in range(len(items))
        }
        for future in as_completed(futures):
            index = futures[future]
            future.result()  # re-raises ProcessingError from the child
            produced[index] = ProducedFile(
                outputs[index],
                f"{file_stem(items[index][1])}.docx",
                media_type=DOCX_MEDIA_TYPE,
            )
            completed += 1
            ctx.report_progress(int(completed / len(items) * 90))
    return [item for item in produced if item is not None]


@celery_app.task(name="tools.pdf-to-word", bind=True)
def pdf_to_word(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        options = ctx.options

        if len(ctx.input_paths) > 1 and can_spawn_processes():
            return _pdf_to_word_parallel(ctx)

        def operate(path, name, index):
            output = ctx.workspace / f"converted-{index}.docx"
            prepared = prepare_pdf_for_conversion(
                path, ctx.workspace, display_name=name
            )
            pdf_to_docx(
                prepared,
                output,
                first_page=options.get("first_page"),
                last_page=options.get("last_page"),
                # Single input: split its pages across processes instead.
                page_workers=page_parallel_workers(prepared),
                display_name=name,
            )
            return ProducedFile(
                output, f"{file_stem(name)}.docx", media_type=DOCX_MEDIA_TYPE
            )

        return process_each_input(ctx, operate)

    run_tool_job(job_id, process)
