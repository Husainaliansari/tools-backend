"""Gunicorn configuration for production.

Run with:
    gunicorn app.main:app -c gunicorn.conf.py

Gunicorn acts as the process manager (mastering multiple workers, graceful
restarts, timeouts) while each worker runs the ASGI app via a Uvicorn worker.
Values are overridable through environment variables (Twelve-Factor App).
"""

from __future__ import annotations

import multiprocessing
import os

# --- Server socket -----------------------------------------------------------
bind = os.getenv(
    "GUNICORN_BIND",
    f"{os.getenv('HOST', '0.0.0.0')}:{os.getenv('PORT', '8000')}",
)
backlog = 2048

# --- Worker processes --------------------------------------------------------
# Rule of thumb: (2 x CPU cores) + 1. Override via WEB_CONCURRENCY.
workers = int(os.getenv("WEB_CONCURRENCY", (multiprocessing.cpu_count() * 2) + 1))
worker_class = "uvicorn_worker.UvicornWorker"
worker_connections = 1000
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5

# Recycle workers periodically to bound memory growth.
max_requests = 1000
max_requests_jitter = 100

# --- Logging -----------------------------------------------------------------
# Emit to stdout/stderr; structlog handles formatting inside the app. In
# systemd/containerised environments logs are collected from these streams.
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# --- Process naming ----------------------------------------------------------
proc_name = "fastapi-backend"

# --- App loading -------------------------------------------------------------
# preload_app is kept False: the async DB engine/Redis pool are created at
# import time, and preloading would fork those handles across workers.
preload_app = False
