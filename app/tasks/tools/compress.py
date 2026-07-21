"""PDF compression worker task (Ghostscript)."""

from __future__ import annotations

from app.tasks.base import (
    ProducedFile,
    ToolRunContext,
    process_each_input,
    run_tool_job,
)
from app.utils.filenames import file_stem
from app.utils.ghostscript import compress_pdf
from app.workers.celery_app import celery_app


@celery_app.task(name="tools.compress", bind=True)
def compress(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        quality = ctx.options.get("quality", "recommended")

        def operate(path, name, index):
            output = compress_pdf(
                path, ctx.workspace / f"compressed-{index}.pdf", quality=quality
            )
            return ProducedFile(output, f"{file_stem(name)}-compressed.pdf")

        return process_each_input(ctx, operate)

    run_tool_job(job_id, process)
