"""Image → PDF worker tasks (img2pdf). One processor serves JPG and PNG."""

from __future__ import annotations

from app.tasks.base import ProducedFile, ToolRunContext, run_tool_job
from app.utils.filenames import file_stem
from app.utils.images import images_to_pdf
from app.workers.celery_app import celery_app


def _combine(ctx: ToolRunContext) -> list[ProducedFile]:
    options = ctx.options
    output = ctx.workspace / "combined.pdf"
    images_to_pdf(
        ctx.input_paths,
        output,
        page_size=options.get("page_size", "fit"),
        orientation=options.get("orientation", "portrait"),
        margin_mm=options.get("margin_mm", 10.0),
        perf=ctx.perf,
    )
    ctx.report_progress(90)
    # A single image keeps its own name; albums get a generic one.
    download_name = (
        f"{file_stem(ctx.input_names[0])}.pdf"
        if len(ctx.input_names) == 1
        else "images.pdf"
    )
    return [ProducedFile(path=output, download_name=download_name)]


@celery_app.task(name="tools.jpg-to-pdf", bind=True)
def jpg_to_pdf(self, job_id: str) -> None:
    run_tool_job(job_id, _combine)


@celery_app.task(name="tools.png-to-pdf", bind=True)
def png_to_pdf(self, job_id: str) -> None:
    run_tool_job(job_id, _combine)
