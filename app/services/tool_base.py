"""Tool base service — the reusable "run a PDF tool" pipeline.

Every tool (Compress, Merge, Split, ...) follows the same lifecycle:

    validate inputs → create job row → link input files → enqueue Celery task

Concrete tools subclass :class:`BaseToolService` and declare *what varies*:
their slug, input constraints and an options schema. The pipeline itself —
validation, persistence, dispatch, failure handling — is written once, here.

The worker-side counterpart lives in ``app/tasks/base.py``.
"""

from __future__ import annotations

import threading
import uuid
from abc import ABC
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.config.plans import limits_for_plan
from app.constants import ErrorCode, JobFileRole, JobStatus, ToolSlug
from app.exceptions.base import ValidationError
from app.exceptions.files import (
    FileNotFoundAppError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.logging import get_logger
from app.models.job import JobFile, ProcessingJob
from app.repositories.file import FileRepository
from app.repositories.job import JobRepository
from app.schemas.response import ErrorDetail
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


class BaseToolService(ABC):
    """Shared job-creation pipeline for all PDF tools."""

    # --- What each concrete tool declares -------------------------------- #
    slug: ClassVar[ToolSlug]
    #: Celery task name; convention: ``tools.<slug>``.
    task_name: ClassVar[str]
    allowed_input_extensions: ClassVar[frozenset[str]] = frozenset({"pdf"})
    min_input_files: ClassVar[int] = 1
    max_input_files: ClassVar[int] = 1
    #: Pydantic model validating the tool's options payload (None = no options).
    options_model: ClassVar[type[BaseModel] | None] = None

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.files = FileRepository(session)
        self.jobs = JobRepository(session)
        self._settings = get_settings()

    # --- Pipeline --------------------------------------------------------- #
    async def create_job(
        self,
        file_ids: list[uuid.UUID],
        options: dict[str, Any] | None = None,
        *,
        user_id: uuid.UUID | None = None,
        plan: str | None = None,
    ) -> ProcessingJob:
        """Validate, persist and enqueue a job. Returns the queued job."""
        validated_options = self._validate_options(options or {})
        input_files = await self._validate_inputs(file_ids, user_id=user_id, plan=plan)

        job = ProcessingJob(
            tool=self.slug.value,
            status=JobStatus.PENDING,
            progress=0,
            options=validated_options,
            user_id=user_id,
            expires_at=datetime.now(UTC)
            + timedelta(hours=self._settings.FILE_RETENTION_HOURS),
        )
        self.jobs.add(job)
        await self.jobs.flush()
        for position, stored_file in enumerate(input_files):
            self.session.add(
                JobFile(
                    job_id=job.id,
                    file_id=stored_file.id,
                    role=JobFileRole.INPUT,
                    position=position,
                )
            )
        # Mark the job queued and commit *before* dispatching: a worker may
        # pick the task up instantly, and nothing must overwrite its status
        # transitions afterwards. The task id is generated here so it can be
        # persisted in the same commit.
        task_id = uuid.uuid4().hex
        job.celery_task_id = task_id
        job.status = JobStatus.QUEUED
        await self.jobs.commit()

        try:
            # Prefer the registered task object: unlike send_task it honours
            # task_always_eager, so dev/test runs execute inline.
            task = celery_app.tasks.get(self.task_name)
            if task is not None:
                if (
                    self._settings.CELERY_TASK_ALWAYS_EAGER
                    and self._settings.CELERY_EAGER_BACKGROUND
                ):
                    # Broker-less dev: eager execution would block this request
                    # for the whole conversion. Run it on a thread instead so
                    # the client gets the job id immediately and polls progress
                    # — the same contract as a real worker deployment.
                    self._dispatch_eager_in_background(task, job.id, task_id)
                else:
                    task.apply_async(args=[str(job.id)], task_id=task_id)
            else:
                celery_app.send_task(
                    self.task_name, args=[str(job.id)], task_id=task_id
                )
        except Exception:
            logger.exception("job_dispatch_failed", job_id=str(job.id), tool=self.slug)
            await self.session.refresh(job)
            job.status = JobStatus.FAILED
            job.error_code = ErrorCode.SERVICE_UNAVAILABLE
            job.error_message = "The processing queue is unavailable. Try again later."
            job.finished_at = datetime.now(UTC)
            await self.jobs.commit()
            return job

        logger.info(
            "job_enqueued",
            job_id=str(job.id),
            tool=self.slug,
            input_files=len(input_files),
        )
        return job

    def _dispatch_eager_in_background(
        self, task: Any, job_id: uuid.UUID, task_id: str
    ) -> None:
        """Run an eager task on a daemon thread (fire-and-forget).

        ``run_tool_job`` owns all failure handling, so the job row always
        reaches a terminal state even if the task body raises.
        """

        def run() -> None:
            try:
                task.apply_async(args=[str(job_id)], task_id=task_id)
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "eager_background_task_failed", job_id=str(job_id), tool=self.slug
                )

        threading.Thread(
            target=run, name=f"eager-{self.slug.value}-{task_id[:8]}", daemon=True
        ).start()

    # --- Validation helpers ------------------------------------------------ #
    def _validate_options(self, options: dict[str, Any]) -> dict[str, Any]:
        if self.options_model is None:
            return {}
        try:
            return self.options_model.model_validate(options).model_dump(mode="json")
        except PydanticValidationError as exc:
            details = [
                ErrorDetail(
                    message=err.get("msg", "Invalid value."),
                    field=".".join(str(loc) for loc in err.get("loc", [])),
                    type=err.get("type"),
                )
                for err in exc.errors()
            ]
            raise ValidationError(
                f"Invalid options for tool '{self.slug}'.", details=details
            ) from exc

    async def _validate_inputs(
        self,
        file_ids: list[uuid.UUID],
        *,
        user_id: uuid.UUID | None = None,
        plan: str | None = None,
    ) -> list:
        if not self.min_input_files <= len(file_ids) <= self.max_input_files:
            raise ValidationError(
                f"Tool '{self.slug}' requires between {self.min_input_files} and "
                f"{self.max_input_files} input files (received {len(file_ids)})."
            )

        # Plan ceilings apply on top of the tool's own range: uploads are
        # already capped per request, but files can be uploaded one at a time,
        # so the batch limits must hold at job creation too.
        limits = limits_for_plan(plan)
        if len(file_ids) > limits.max_files:
            raise ValidationError(
                f"The {limits.label} plan allows at most {limits.max_files} "
                f"files per task (received {len(file_ids)})."
            )

        input_files = []
        for file_id in file_ids:
            record = await self.files.get_active(file_id, user_id=user_id)
            if record is None:
                raise FileNotFoundAppError(f"Input file {file_id} was not found.")
            if record.extension not in self.allowed_input_extensions:
                raise UnsupportedFileTypeError(
                    f"'{record.original_name}' (.{record.extension}) is not "
                    f"accepted by tool '{self.slug}'."
                )
            if record.size_bytes > limits.max_file_size_bytes:
                raise FileTooLargeError(
                    f"'{record.original_name}' exceeds the "
                    f"{limits.max_file_size_mb} MB per-file limit of the "
                    f"{limits.label} plan."
                )
            input_files.append(record)

        total_bytes = sum(record.size_bytes for record in input_files)
        if total_bytes > limits.max_total_size_bytes:
            raise FileTooLargeError(
                f"The combined input size exceeds the "
                f"{limits.max_total_size_mb} MB limit of the {limits.label} plan."
            )
        return input_files
