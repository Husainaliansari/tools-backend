"""Document worker tasks: metadata, compare, redact, fill-forms, sign."""

from __future__ import annotations

from app.exceptions.jobs import ProcessingError
from app.tasks.base import (
    ProducedFile,
    ToolRunContext,
    process_each_input,
    run_tool_job,
)
from app.utils.filenames import IMAGE_EXTENSIONS, file_extension, file_stem
from app.utils.pdf_document import compare_pdfs, fill_form, redact_text, set_metadata
from app.utils.pdf_overlay import MM_TO_PT, make_signature_draw, overlay_pdf
from app.workers.celery_app import celery_app


@celery_app.task(name="tools.metadata", bind=True)
def metadata(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        options = ctx.options
        fields = {
            key: options[key]
            for key in ("title", "author", "subject", "keywords")
            if options.get(key)
        }

        def operate(path, name, index):
            output = ctx.workspace / f"meta-{index}.pdf"
            set_metadata(
                path,
                output,
                fields=fields,
                clear_existing=options.get("clear_existing", False),
            )
            return ProducedFile(output, f"{file_stem(name)}-metadata.pdf")

        return process_each_input(ctx, operate)

    run_tool_job(job_id, process)


@celery_app.task(name="tools.compare", bind=True)
def compare(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        report = ctx.workspace / "comparison-report.pdf"
        compare_pdfs(ctx.input_paths[0], ctx.input_paths[1], report)
        ctx.report_progress(90)
        return [ProducedFile(report, "comparison-report.pdf")]

    run_tool_job(job_id, process)


@celery_app.task(name="tools.redact", bind=True)
def redact(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        def operate(path, name, index):
            output = ctx.workspace / f"redacted-{index}.pdf"
            redact_text(
                path,
                output,
                texts=ctx.options.get("texts") or [],
                areas=ctx.options.get("areas") or [],
            )
            return ProducedFile(output, f"{file_stem(name)}-redacted.pdf")

        return process_each_input(ctx, operate)

    run_tool_job(job_id, process)


@celery_app.task(name="tools.fill-forms", bind=True)
def fill_forms(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        output = ctx.workspace / "filled.pdf"
        fill_form(ctx.input_paths[0], output, fields=ctx.options["fields"])
        ctx.report_progress(90)
        return [ProducedFile(output, f"{file_stem(ctx.input_names[0])}-filled.pdf")]

    run_tool_job(job_id, process)


@celery_app.task(name="tools.sign", bind=True)
def sign(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        options = ctx.options
        pairs = list(zip(ctx.input_paths, ctx.input_names, strict=True))
        images = [p for p, n in pairs if file_extension(n) in IMAGE_EXTENSIONS]
        pdfs = [(p, n) for p, n in pairs if file_extension(n) == "pdf"]
        if not images:
            raise ProcessingError("Add a JPG or PNG of your signature.")
        if not pdfs:
            raise ProcessingError("No PDF to sign was provided.")

        draw = make_signature_draw(
            images[0],
            target_page=options.get("page"),
            position=options.get("position", "bottom-right"),
            scale=options.get("scale", 0.25),
            margin_pt=options.get("margin_mm", 15.0) * MM_TO_PT,
        )

        def operate(path, name, index):
            output = ctx.workspace / f"signed-{index}.pdf"
            overlay_pdf(path, output, draw)
            return ProducedFile(output, f"{file_stem(name)}-signed.pdf")

        return process_each_input(ctx, operate, items=pdfs)

    run_tool_job(job_id, process)
