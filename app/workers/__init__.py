"""Workers package.

Holds the Celery application definition and worker-level configuration. Kept
separate from ``app/tasks`` (the task implementations) so infrastructure and
business tasks evolve independently (Separation of Concerns).
"""

from app.workers.celery_app import celery_app

__all__ = ["celery_app"]
