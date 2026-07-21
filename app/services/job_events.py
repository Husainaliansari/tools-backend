"""Job progress event publishing (Redis pub/sub).

Workers publish an event whenever a job's status or progress changes; the
WebSocket endpoint subscribes and pushes to clients immediately instead of
polling. Everything here fails silent — progress events are an optimisation,
never a dependency: consumers always fall back to reading the job row.
"""

from __future__ import annotations

import json

import redis as sync_redis

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_publisher: sync_redis.Redis | None = None


def job_channel(job_id: str) -> str:
    return f"job-events:{job_id}"


def _get_publisher() -> sync_redis.Redis:
    global _publisher
    if _publisher is None:
        settings = get_settings()
        _publisher = sync_redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
    return _publisher


def publish_job_event(
    job_id: str, *, status: str, progress: int, error_code: str | None = None
) -> None:
    """Publish a progress event from a (synchronous) worker. Never raises."""
    payload = json.dumps(
        {
            "id": job_id,
            "status": status,
            "progress": progress,
            "error_code": error_code,
        }
    )
    try:
        _get_publisher().publish(job_channel(job_id), payload)
    except Exception:  # Redis down — clients fall back to polling
        logger.debug("job_event_publish_failed", job_id=job_id)
