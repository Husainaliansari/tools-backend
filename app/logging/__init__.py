"""Logging package.

Public surface for logging configuration and logger acquisition::

    from app.logging import configure_logging, get_logger

    configure_logging()
    log = get_logger(__name__)
    log.info("something happened", key="value")
"""

from app.logging.config import configure_logging, get_logger

__all__ = ["configure_logging", "get_logger"]
