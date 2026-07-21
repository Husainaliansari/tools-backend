"""Overlay-stamping worker tasks: watermark, header & footer, page numbers.

All three run the same per-file loop — build a draw function from the job's
options, apply it through the shared overlay engine.
"""

from __future__ import annotations

from app.exceptions.jobs import ProcessingError
from app.tasks.base import (
    ProducedFile,
    ToolRunContext,
    process_each_input,
    run_tool_job,
)
from app.utils.filenames import IMAGE_EXTENSIONS, file_extension, file_stem
from app.utils.pdf_overlay import (
    MM_TO_PT,
    DrawFn,
    PageFilter,
    make_header_footer_draw,
    make_image_watermark_draw,
    make_page_number_draw,
    make_watermark_draw,
    overlay_pdf,
    parse_page_selection,
)
from app.workers.celery_app import celery_app


def _stamp_all(
    ctx: ToolRunContext,
    draw: DrawFn,
    *,
    suffix: str,
    page_filter: PageFilter | None = None,
    only_pdfs: bool = False,
    under: bool = False,
) -> list[ProducedFile]:
    pairs = list(zip(ctx.input_paths, ctx.input_names, strict=True))
    if only_pdfs:
        pairs = [(p, n) for p, n in pairs if file_extension(n) == "pdf"]
    if not pairs:
        raise ProcessingError("No PDF files to stamp were provided.")

    def operate(path, name, index):
        output = ctx.workspace / f"stamped-{index}.pdf"
        overlay_pdf(
            path,
            output,
            draw,
            page_filter=page_filter,
            under=under,
            display_name=file_stem(name),
        )
        return ProducedFile(output, f"{file_stem(name)}-{suffix}.pdf")

    return process_each_input(ctx, operate, items=pairs)


@celery_app.task(name="tools.watermark", bind=True)
def watermark(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        options = ctx.options
        placement = dict(
            position=options.get("position", "center"),
            offset_x_pt=options.get("offset_x_mm", 0.0) * MM_TO_PT,
            offset_y_pt=options.get("offset_y_mm", 0.0) * MM_TO_PT,
            margin_pt=options.get("margin_mm", 12.0) * MM_TO_PT,
            tile=options.get("tile", False),
        )
        if options.get("mode", "text") == "image":
            images = [
                path
                for path, name in zip(ctx.input_paths, ctx.input_names, strict=True)
                if file_extension(name) in IMAGE_EXTENSIONS
            ]
            if not images:
                raise ProcessingError(
                    "Image watermark mode requires a JPG or PNG input file."
                )
            draw = make_image_watermark_draw(
                images[0],
                opacity=options.get("opacity", 0.15),
                rotation=options.get("rotation", 45),
                scale=options.get("scale", 0.5),
                keep_aspect=options.get("keep_aspect", True),
                scale_x=options.get("scale_x"),
                scale_y=options.get("scale_y"),
                **placement,
            )
        else:
            draw = make_watermark_draw(
                options["text"],
                font_size=options.get("font_size", 48),
                opacity=options.get("opacity", 0.15),
                rotation=options.get("rotation", 45),
                color=options.get("color", "#808080"),
                font_family=options.get("font_family", "helvetica"),
                bold=options.get("bold", True),
                italic=options.get("italic", False),
                underline=options.get("underline", False),
                align=options.get("align", "center"),
                letter_spacing=options.get("letter_spacing", 0.0),
                line_height=options.get("line_height", 1.2),
                **placement,
            )
        return _stamp_all(
            ctx,
            draw,
            suffix="watermarked",
            page_filter=parse_page_selection(
                options.get("pages", "all"), options.get("page_range")
            ),
            only_pdfs=True,
            under=options.get("layer", "above") == "below",
        )

    run_tool_job(job_id, process)


@celery_app.task(name="tools.header-footer", bind=True)
def header_footer(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        options = ctx.options
        draw = make_header_footer_draw(
            options.get("header_text"),
            options.get("footer_text"),
            font_size=options.get("font_size", 10),
            color=options.get("color", "#333333"),
            margin_pt=options.get("margin_mm", 12.0) * MM_TO_PT,
            align=options.get("align", "center"),
            header_align=options.get("header_align"),
            footer_align=options.get("footer_align"),
            font_family=options.get("font_family", "helvetica"),
            bold=options.get("bold", False),
            italic=options.get("italic", False),
            opacity=options.get("opacity", 1.0),
        )
        return _stamp_all(
            ctx,
            draw,
            suffix="headers",
            page_filter=parse_page_selection(
                options.get("pages", "all"), options.get("page_range")
            ),
        )

    run_tool_job(job_id, process)


@celery_app.task(name="tools.page-numbers", bind=True)
def page_numbers(self, job_id: str) -> None:
    def process(ctx: ToolRunContext) -> list[ProducedFile]:
        options = ctx.options
        draw = make_page_number_draw(
            options.get("format", "{page}"),
            position=options.get("position", "bottom-center"),
            font_size=options.get("font_size", 10),
            color=options.get("color", "#333333"),
            margin_pt=options.get("margin_mm", 12.0) * MM_TO_PT,
            number_offset=options.get("start_at", 1) - 1,
        )
        page_filter: PageFilter | None = (
            (lambda page, _total: page != 1) if options.get("skip_first") else None
        )
        return _stamp_all(ctx, draw, suffix="numbered", page_filter=page_filter)

    run_tool_job(job_id, process)
