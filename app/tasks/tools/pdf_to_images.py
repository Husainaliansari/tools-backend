"""PDF to image worker tasks (Poppler pdftoppm).

One shared processor parameterised by output format serves both the JPG and
PNG tools — the pipeline is identical apart from the render flag and media
type.
"""

from __future__ import annotations

from app.tasks.base import (
    ProducedFile,
    ToolRunContext,
    process_each_input,
    run_tool_job,
)
from app.utils.filenames import file_stem
from app.utils.pdf_pages import page_count
from app.utils.poppler import ImageFormat, pdf_to_images_auto
from app.workers.celery_app import celery_app

_MEDIA_TYPES: dict[ImageFormat, str] = {"jpeg": "image/jpeg", "png": "image/png"}
_EXTENSIONS: dict[ImageFormat, str] = {"jpeg": "jpg", "png": "png"}


def _render_all(ctx: ToolRunContext, image_format: ImageFormat) -> list[ProducedFile]:
    options = ctx.options
    extension = _EXTENSIONS[image_format]
    media_type = _MEDIA_TYPES[image_format]

    def operate(path, name, index):
        pages = pdf_to_images_auto(
            path,
            ctx.workspace,
            total_pages=page_count(path),
            image_format=image_format,
            dpi=options.get("dpi", 150),
            quality=options.get("quality", 90),
            grayscale=options.get("grayscale", False),
            first_page=options.get("first_page"),
            last_page=options.get("last_page"),
            display_name=name,
        )
        stem = file_stem(name)
        return [
            ProducedFile(
                page_path,
                # Single-page results keep a clean name; multi-page get -page-N.
                (
                    f"{stem}.{extension}"
                    if len(pages) == 1
                    else f"{stem}-page-{page_number:02d}.{extension}"
                ),
                media_type=media_type,
            )
            for page_number, page_path in pages
        ]

    return process_each_input(ctx, operate)


@celery_app.task(name="tools.pdf-to-jpg", bind=True)
def pdf_to_jpg(self, job_id: str) -> None:
    run_tool_job(job_id, lambda ctx: _render_all(ctx, "jpeg"))


@celery_app.task(name="tools.pdf-to-png", bind=True)
def pdf_to_png(self, job_id: str) -> None:
    run_tool_job(job_id, lambda ctx: _render_all(ctx, "png"))
