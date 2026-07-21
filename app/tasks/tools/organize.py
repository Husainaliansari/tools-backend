"""Organize worker tasks: merge, split, rotate, delete/extract/reorder pages."""

from __future__ import annotations

from app.tasks.base import (
    ProducedFile,
    ToolRunContext,
    process_each_input,
    run_tool_job,
)
from app.utils import pdf_pages
from app.utils.filenames import file_stem
from app.workers.celery_app import celery_app


def _single_output_tool(task_name: str, suffix: str, operation) -> None:
    """Register a task whose per-input operation yields one output PDF."""

    @celery_app.task(name=task_name, bind=True)
    def task(self, job_id: str) -> None:
        def process(ctx: ToolRunContext) -> list[ProducedFile]:
            def operate(path, name, index):
                output = ctx.workspace / f"out-{index}.pdf"
                operation(path, output, ctx.options)
                return ProducedFile(output, f"{file_stem(name)}-{suffix}.pdf")

            return process_each_input(ctx, operate)

        run_tool_job(job_id, process)


@celery_app.task(name="tools.merge", bind=True)
def merge(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        output = ctx.workspace / "merged.pdf"
        pdf_pages.merge_pdfs(ctx.input_paths, output)
        ctx.report_progress(90)
        return [ProducedFile(output, "merged.pdf")]

    run_tool_job(job_id, process)


@celery_app.task(name="tools.split", bind=True)
def split(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        options = ctx.options
        stem = file_stem(ctx.input_names[0])
        parts = pdf_pages.split_pdf(
            ctx.input_paths[0],
            ctx.workspace,
            ranges=options.get("ranges"),
            every_page=options.get("mode") == "every_page",
        )
        ctx.report_progress(90)
        return [
            ProducedFile(path, f"{stem}-pages-{label}.pdf") for label, path in parts
        ]

    run_tool_job(job_id, process)


_single_output_tool(
    "tools.rotate",
    "rotated",
    lambda src, dst, options: pdf_pages.rotate_pdf(
        src,
        dst,
        angle=options.get("angle", 90),
        pages=options.get("pages"),
        apply_to=options.get("apply_to", "all"),
    ),
)

_single_output_tool(
    "tools.delete-pages",
    "edited",
    lambda src, dst, options: pdf_pages.delete_pages(src, dst, pages=options["pages"]),
)

_single_output_tool(
    "tools.extract-pages",
    "extracted",
    lambda src, dst, options: pdf_pages.extract_pages(src, dst, pages=options["pages"]),
)

_single_output_tool(
    "tools.reorder",
    "reordered",
    lambda src, dst, options: pdf_pages.reorder_pages(src, dst, order=options["order"]),
)
