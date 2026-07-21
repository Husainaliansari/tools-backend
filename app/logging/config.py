"""Structlog + stdlib logging configuration.

A single ``configure_logging()`` call wires structlog and the standard library
``logging`` module together so that:

* Application logs use structlog's ergonomic, structured API.
* Third-party / framework logs (uvicorn, gunicorn, sqlalchemy) are routed
  through the same processor chain and rendered identically.
* Every record carries the ``request_id`` / ``correlation_id`` bound by the
  request-context middleware (via ``merge_contextvars``).
* Output is JSON in production and human-readable in development, controlled by
  the ``LOG_RENDERER`` setting.

This function is idempotent and safe to call once at process startup.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import structlog

from app.config import get_settings


def configure_logging() -> None:
    """Configure structlog and the stdlib logging bridge for the whole app."""
    settings = get_settings()

    # Processors shared by both structlog-native and stdlib log records.
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Choose the final renderer based on environment.
    if settings.LOG_RENDERER == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog itself.
    structlog.configure(
        processors=[
            *shared_processors,
            # Prepare event dict for the stdlib ProcessorFormatter.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Formatter that renders records originating from *stdlib* loggers using the
    # same processor chain, so framework logs match application logs.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.LOG_LEVEL)

    # Rotating file log under <STORAGE_ROOT>/logs/ — always JSON so the files
    # are machine-parseable regardless of the console renderer.
    if settings.LOG_TO_FILE:
        settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        file_formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
        file_handler = RotatingFileHandler(
            settings.LOGS_DIR / "app.log",
            maxBytes=settings.LOG_FILE_MAX_BYTES,
            backupCount=settings.LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Let uvicorn/gunicorn records propagate to the root handler instead of
    # using their own formatters, so all output is consistent.
    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "gunicorn",
        "gunicorn.error",
        "gunicorn.access",
    ):
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers.clear()
        logging_logger.propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger. Preferred entry point for app code."""
    return structlog.stdlib.get_logger(name)
