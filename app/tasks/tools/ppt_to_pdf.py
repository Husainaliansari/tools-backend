"""PPT to PDF worker task (LibreOffice)."""

from __future__ import annotations

from app.tasks.base import (
    ProducedFile,
    ToolRunContext,
    process_each_input_parallel,
    run_tool_job,
)
from app.utils.filenames import file_stem
from app.utils.office import (
    FilterValue,
    libreoffice_convert,
    office_conversion_slots,
)
from app.workers.celery_app import celery_app


def _export_filter(options: dict) -> tuple[str | None, dict[str, FilterValue]]:
    """Map validated tool options onto Impress PDF-export filter options."""
    filter_options: dict[str, FilterValue] = {}
    if options.get("pdf_a"):
        filter_options["SelectPdfVersion"] = 2  # PDF/A-2b
    if options.get("slide_range"):
        filter_options["PageRange"] = options["slide_range"]
    return ("impress_pdf_Export" if filter_options else None), filter_options


@celery_app.task(name="tools.ppt-to-pdf", bind=True)
def ppt_to_pdf(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        filter_name, filter_options = _export_filter(ctx.options)

        def operate(path, name, index):
            output = libreoffice_convert(
                path,
                ctx.workspace,
                filter_name=filter_name,
                filter_options=filter_options or None,
                display_name=name,
            )
            return ProducedFile(output, f"{file_stem(name)}.pdf")

        # Presentations convert independently — run them concurrently, one
        # per available conversion slot (warm unoserver / soffice profile).
        return process_each_input_parallel(
            ctx, operate, max_workers=office_conversion_slots()
        )

    run_tool_job(job_id, process)
