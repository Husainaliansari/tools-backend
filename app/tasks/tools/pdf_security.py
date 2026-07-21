"""PDF security worker tasks: remove watermark, protect (encrypt), unlock."""

from __future__ import annotations

from app.exceptions.jobs import ProcessingError
from app.tasks.base import (
    ProducedFile,
    ToolRunContext,
    process_each_input,
    run_tool_job,
)
from app.utils.filenames import file_stem
from app.utils.pdf_pages import unlock_pdf
from app.utils.pdf_security import encrypt_pdf, remove_watermarks
from app.workers.celery_app import celery_app


@celery_app.task(name="tools.remove-watermark", bind=True)
def remove_watermark(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        def operate(path, name, index):
            output = ctx.workspace / f"clean-{index}.pdf"
            text = ctx.options.get("text")
            removed = remove_watermarks(
                path,
                output,
                mode=ctx.options.get("mode", "both"),
                text=text,
            )
            # A text-targeted run that removed nothing would silently return
            # the input unchanged — fail with actionable guidance instead.
            if text and removed == 0:
                raise ProcessingError(
                    f'No watermark matching "{text}" was found in "{name}", '
                    "and automatic detection found nothing else to remove. "
                    "Make sure the text matches the watermark exactly as it "
                    "appears. Watermarks that are part of a scanned or "
                    "flattened image cannot be separated from the page."
                )
            return ProducedFile(output, f"{file_stem(name)}-no-watermark.pdf")

        return process_each_input(ctx, operate)

    run_tool_job(job_id, process)


@celery_app.task(name="tools.protect", bind=True)
def protect(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        options = ctx.options

        def operate(path, name, index):
            output = ctx.workspace / f"protected-{index}.pdf"
            encrypt_pdf(
                path,
                output,
                user_password=options["user_password"],
                owner_password=options.get("owner_password"),
                allow_printing=options.get("allow_printing", True),
                allow_copying=options.get("allow_copying", False),
                allow_modification=options.get("allow_modification", False),
            )
            return ProducedFile(output, f"{file_stem(name)}-protected.pdf")

        return process_each_input(ctx, operate)

    # Passwords must not survive in the persisted job options.
    run_tool_job(
        job_id, process, redact_option_keys=("user_password", "owner_password")
    )


@celery_app.task(name="tools.unlock", bind=True)
def unlock(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        def operate(path, name, index):
            output = ctx.workspace / f"unlocked-{index}.pdf"
            unlock_pdf(path, output, password=ctx.options["password"])
            return ProducedFile(output, f"{file_stem(name)}-unlocked.pdf")

        return process_each_input(ctx, operate)

    run_tool_job(job_id, process, redact_option_keys=("password",))
