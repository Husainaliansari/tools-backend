"""Worker-side tool-job runner — the reusable execution pipeline.

Mirrors ``app/services/tool_base.py`` on the worker side. A concrete tool task
only supplies a *processor* function; everything else is handled here:

* load the job + input files (sync session — Celery workers are synchronous),
* transition status ``queued → processing → completed/failed``,
* create a scratch workspace under ``temp/`` and always clean it up,
* import produced files into ``processed/``, register rows and link them,
* translate failures into ``error_code``/``error_message`` on the job row.

A concrete tool task looks like::

    @celery_app.task(name="tools.compress", bind=True)
    def compress_pdf(self, job_id: str) -> None:
        def process(ctx: ToolRunContext) -> list[ProducedFile]:
            out = ctx.workspace / "compressed.pdf"
            run_command([...ghostscript...])
            ctx.report_progress(80)
            return [ProducedFile(path=out, download_name="compressed.pdf")]

        run_tool_job(job_id, process)
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.constants import (
    ErrorCode,
    FileCategory,
    FileStatus,
    JobFileRole,
    JobStatus,
)
from app.db.sync_session import sync_session
from app.exceptions.jobs import ProcessingError
from app.logging import get_logger
from app.models.file import StoredFile
from app.models.job import JobFile, ProcessingJob
from app.repositories.job import SyncJobRepository
from app.services.job_events import publish_job_event
from app.services.storage import get_storage
from app.services.temp_files import temp_workspace
from app.utils.command import CommandError
from app.utils.perf import NULL_TIMER, PerfTimer
from app.utils.filenames import file_extension, sanitize_filename
from app.utils.hashing import sha256_file

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProducedFile:
    """A file created by a tool processor, awaiting import into processed/."""

    path: Path
    #: Name offered to the user on download (Content-Disposition).
    download_name: str
    media_type: str = "application/pdf"


@dataclass
class ToolRunContext:
    """Everything a tool processor needs to do its work."""

    job: ProcessingJob
    #: Absolute paths of the job's input files, in their linked order.
    input_paths: list[Path]
    #: Original (client-supplied, sanitised) names of the inputs, same order.
    #: Tools use these to derive friendly output names.
    input_names: list[str]
    #: The job's validated options payload.
    options: dict[str, Any]
    #: Scratch directory; removed automatically after the run.
    workspace: Path
    #: Call with 0-100 to surface progress through the status API.
    report_progress: Callable[[int], None] = field(default=lambda _p: None)
    #: Per-job phase timer. Processors call ``ctx.perf.phase("name")`` to
    #: record conversion sub-phases; the runner logs the aggregate as
    #: ``job_perf``. Defaults to a no-op timer.
    perf: PerfTimer = field(default_factory=lambda: NULL_TIMER)


Processor = Callable[[ToolRunContext], list[ProducedFile]]

#: What a per-file operation may return: one output, or several (e.g. pages).
InputResult = ProducedFile | list[ProducedFile]


def process_each_input(
    ctx: ToolRunContext,
    operate: Callable[[Path, str, int], InputResult],
    *,
    items: list[tuple[Path, str]] | None = None,
    progress_ceiling: int = 90,
) -> list[ProducedFile]:
    """Run a per-file operation over the job's inputs with progress reporting.

    The canonical tool-task loop, shared by every tool that maps inputs to
    outputs independently. ``operate(path, original_name, index)`` returns the
    produced file(s) for that input. ``items`` overrides the default input
    list for tools that pre-filter (e.g. stamping only the PDF inputs).
    Progress climbs to ``progress_ceiling``, leaving headroom for output
    import after the last file.
    """
    pairs = (
        items
        if items is not None
        else list(zip(ctx.input_paths, ctx.input_names, strict=True))
    )
    produced: list[ProducedFile] = []
    for index, (path, name) in enumerate(pairs):
        result = operate(path, name, index)
        produced.extend(result if isinstance(result, list) else [result])
        ctx.report_progress(int((index + 1) / len(pairs) * progress_ceiling))
    return produced


def process_each_input_parallel(
    ctx: ToolRunContext,
    operate: Callable[[Path, str, int], InputResult],
    *,
    max_workers: int,
    items: list[tuple[Path, str]] | None = None,
    progress_ceiling: int = 90,
) -> list[ProducedFile]:
    """:func:`process_each_input`, but per-file operations run concurrently.

    Threads suit subprocess-bound operations (LibreOffice, Ghostscript, ...):
    the GIL is released while waiting on the child process. ``max_workers``
    should be the underlying engine's real capacity (e.g.
    ``office_conversion_slots()``) — oversubscribing only queues work inside
    the engine. Progress advances as files finish; a wall of N similar files
    completes in roughly the slowest file's time instead of the sum.

    The DB-touching ``ctx.report_progress`` is only ever called from this
    (the task's) thread — worker threads run ``operate`` alone, so the
    session stays single-threaded. Output order matches input order. The
    first failure propagates after in-flight files finish, matching the
    sequential helper's job-fails-whole semantics.
    """
    pairs = (
        items
        if items is not None
        else list(zip(ctx.input_paths, ctx.input_names, strict=True))
    )
    workers = min(max_workers, len(pairs))
    if workers <= 1:
        return process_each_input(
            ctx, operate, items=pairs, progress_ceiling=progress_ceiling
        )

    results: list[InputResult | None] = [None] * len(pairs)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(operate, path, name, index): index
            for index, (path, name) in enumerate(pairs)
        }
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()  # re-raises the operation's error
            completed += 1
            ctx.report_progress(int(completed / len(pairs) * progress_ceiling))

    produced: list[ProducedFile] = []
    for result in results:
        if result is not None:
            produced.extend(result if isinstance(result, list) else [result])
    return produced


def run_tool_job(
    job_id: str,
    processor: Processor,
    *,
    redact_option_keys: tuple[str, ...] = (),
) -> None:
    """Execute a tool processor inside the standard job lifecycle.

    ``redact_option_keys`` names options (e.g. passwords) that are scrubbed
    from the persisted job row once the job reaches a terminal state — the
    worker needs them during processing, but they must not live on in the
    database afterwards.
    """
    settings = get_settings()
    storage = get_storage()
    job_uuid = uuid.UUID(job_id)

    with sync_session() as session:
        repo = SyncJobRepository(session)
        job = repo.get_with_files(job_uuid)
        if job is None:
            logger.error("job_missing", job_id=job_id)
            return
        if JobStatus(job.status).is_terminal:
            logger.warning("job_already_terminal", job_id=job_id, status=job.status)
            return

        repo.mark_processing(job)
        session.commit()
        publish_job_event(job_id, status=str(job.status), progress=job.progress)

        input_links = sorted(
            (link for link in job.files if link.role == JobFileRole.INPUT),
            key=lambda link: link.position,
        )
        perf = PerfTimer()
        try:
            with perf.phase("load_inputs"):
                input_paths = [
                    storage.resolve(link.file.category, link.file.relative_path)
                    for link in input_links
                ]
                missing = [p for p in input_paths if not p.is_file()]
                input_bytes = sum(p.stat().st_size for p in input_paths if p.is_file())
            if missing:
                raise ProcessingError(
                    "One or more input files are no longer available.",
                    error_code=ErrorCode.FILE_EXPIRED,
                )

            def report_progress(progress: int) -> None:
                repo.set_progress(job, progress)
                session.commit()
                publish_job_event(job_id, status=str(job.status), progress=job.progress)

            with temp_workspace(prefix=job.tool) as workspace:
                context = ToolRunContext(
                    job=job,
                    input_paths=input_paths,
                    input_names=[link.file.original_name for link in input_links],
                    options=dict(job.options or {}),
                    workspace=workspace,
                    report_progress=report_progress,
                    perf=perf,
                )
                with perf.phase("convert"):
                    produced = processor(context)
                if not produced:
                    raise ProcessingError("The tool produced no output.")
                with perf.phase("export_outputs"):
                    _register_outputs(session, job, produced, settings=settings)

            repo.mark_completed(job)
            session.commit()
            logger.info(
                "job_completed",
                job_id=job_id,
                tool=job.tool,
                input_files=len(input_paths),
                input_bytes=input_bytes,
                output_files=len(produced),
                **perf.summary(),
            )

        except ProcessingError as exc:
            repo.mark_failed(job, error_code=exc.error_code, error_message=exc.message)
            session.commit()
            logger.warning(
                "job_failed", job_id=job_id, tool=job.tool, error_code=exc.error_code
            )
        except CommandError as exc:
            # str(exc) is operator-speak ("Command 'soffice' exited with code
            # 1") — log it, but store a message the user can act on.
            if exc.timed_out:
                code = ErrorCode.PROCESSING_TIMEOUT
                message = (
                    "Processing took too long and was stopped. Very large or "
                    "complex files can exceed the server's time limit — try a "
                    "smaller file or split it into parts."
                )
            else:
                code = ErrorCode.PROCESSING_FAILED
                message = (
                    "The converter could not process this file. It may be "
                    "corrupted, password-protected, or use features the "
                    "converter does not support."
                )
            repo.mark_failed(job, error_code=code, error_message=message)
            session.commit()
            logger.error(
                "job_command_failed",
                job_id=job_id,
                tool=job.tool,
                command=exc.command[0] if exc.command else None,
                returncode=exc.returncode,
                timed_out=exc.timed_out,
                stderr=exc.stderr[:500],
            )
        except Exception as exc:  # never let a job row dangle in 'processing'
            repo.mark_failed(
                job,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
                error_message=f"Unexpected error: {exc}",
            )
            session.commit()
            logger.exception("job_crashed", job_id=job_id, tool=job.tool)
        finally:
            if redact_option_keys and job.options:
                job.options = {
                    key: ("[redacted]" if key in redact_option_keys else value)
                    for key, value in job.options.items()
                }
                session.commit()
            # Terminal push so WebSocket clients learn the outcome instantly.
            publish_job_event(
                job_id,
                status=str(job.status),
                progress=job.progress,
                error_code=job.error_code,
            )


def _register_outputs(
    session: Any,
    job: ProcessingJob,
    produced: list[ProducedFile],
    *,
    settings: Any,
) -> None:
    """Import produced files into processed/ and link them to the job."""
    storage = get_storage()
    expires_at = datetime.now(UTC) + timedelta(hours=settings.FILE_RETENTION_HOURS)

    for position, item in enumerate(produced):
        extension = file_extension(item.download_name) or file_extension(item.path.name)
        allocated, size = storage.import_file(
            item.path, FileCategory.PROCESSED, extension=extension
        )
        record = StoredFile(
            original_name=sanitize_filename(item.download_name),
            stored_name=allocated.stored_name,
            category=FileCategory.PROCESSED,
            relative_path=allocated.relative_path,
            media_type=item.media_type,
            extension=extension,
            size_bytes=size,
            checksum_sha256=sha256_file(allocated.absolute_path),
            status=FileStatus.ACTIVE,
            expires_at=expires_at,
            user_id=job.user_id,  # outputs inherit the job's owner
        )
        session.add(record)
        session.flush()
        session.add(
            JobFile(
                job_id=job.id,
                file_id=record.id,
                role=JobFileRole.OUTPUT,
                position=position,
            )
        )
