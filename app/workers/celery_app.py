"""Celery application factory and configuration.

Tasks live under ``app/tasks/`` and are auto-discovered here.

Start a worker (PDF tools are CPU/subprocess heavy — one task per process)::

    celery -A app.workers.celery_app.celery_app worker --loglevel=info

Start the Beat scheduler (drives the periodic cleanup task)::

    celery -A app.workers.celery_app.celery_app beat --loglevel=info

Broker and result backend default to the configured Redis instance unless
explicit ``CELERY_*`` settings are provided.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "app",
    broker=settings.effective_celery_broker_url,
    backend=settings.effective_celery_result_backend,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=270,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    result_expires=3600,
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    # Route all PDF-tool tasks (named "tools.<slug>") to a dedicated queue so
    # heavyweight conversions never starve lightweight maintenance work.
    task_routes={
        "tools.*": {"queue": "pdf"},
        "maintenance.*": {"queue": "maintenance"},
    },
    task_default_queue="default",
    # Celery Beat: periodic maintenance schedule.
    beat_schedule={
        "cleanup-expired-files-and-jobs": {
            "task": "maintenance.cleanup_expired",
            "schedule": settings.CLEANUP_INTERVAL_MINUTES * 60.0,
        },
    },
)

# Discover task modules registered under the app.tasks package.
celery_app.autodiscover_tasks(["app.tasks"])


@worker_ready.connect
def _prewarm_office(**_kwargs: object) -> None:
    """Seed the LibreOffice profile template before the first conversion job."""
    from app.utils.office import prewarm_office_runtime

    prewarm_office_runtime()

# Import task modules eagerly so tasks are registered in *every* process —
# the API needs them for apply_async dispatch (and eager test execution), not
# just the worker. Bottom of module: task modules import `celery_app` from
# here, so this must run after it is defined.
from app import tasks as _tasks  # noqa: E402,F401
