"""Shared pytest configuration and fixtures.

Establishes the ``testing`` environment before the application is imported and
provides an async HTTP client wired to the ASGI app (with lifespan handling).
No tests are written in the foundation — only the harness.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure settings resolve to the testing profile *before* the app is imported,
# and isolate the storage tree so tests never touch the real one.
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault(
    "STORAGE_ROOT", tempfile.mkdtemp(prefix="pdf-tools-test-storage-")
)
os.environ.setdefault("LOG_TO_FILE", "false")
# Tool jobs execute inline (no broker) so E2E tests cover the worker pipeline.
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
# Inline means *synchronous*: tests assert final job state right after POST,
# so never let the dev .env's background-thread dispatch leak in here.
os.environ["CELERY_EAGER_BACKGROUND"] = "false"
# Isolated database for tests (created on demand by the `database` fixture).
os.environ.setdefault("POSTGRES_DB", "app_test")
# Route external tool invocations to CLI-compatible stub converters.
_FIXTURES = Path(__file__).parent / "fixtures"
os.environ.setdefault(
    "SOFFICE_BIN", f'"{sys.executable}" "{_FIXTURES / "fake_soffice.py"}"'
)
# Pin the classic engine: the managed unoserver pool would otherwise probe
# this machine (and could find a real install). Pool tests opt in explicitly.
os.environ.setdefault("OFFICE_ENGINE", "soffice")
os.environ.setdefault(
    "PDFTOPPM_BIN", f'"{sys.executable}" "{_FIXTURES / "fake_pdftoppm.py"}"'
)
os.environ.setdefault(
    "GHOSTSCRIPT_BIN", f'"{sys.executable}" "{_FIXTURES / "fake_gs.py"}"'
)
os.environ.setdefault(
    "OCRMYPDF_BIN", f'"{sys.executable}" "{_FIXTURES / "fake_ocrmypdf.py"}"'
)
os.environ.setdefault(
    "TESSERACT_BIN", f'"{sys.executable}" "{_FIXTURES / "fake_tesseract.py"}"'
)
# Repair uses the in-process libqpdf (pikepdf) binding — no external binary,
# so no QPDF stub is wired here.
# The suite performs many rapid uploads; never rate-limit tests.
os.environ.setdefault("UPLOAD_RATE_LIMIT_PER_MINUTE", "0")

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """Provide a single application instance for the test session."""
    return create_app()


@pytest.fixture(scope="session")
def database() -> None:
    """Create + migrate the isolated test database; skip if Postgres is down."""
    import psycopg

    from app.config import get_settings

    settings = get_settings()
    dsn = (
        f"host={settings.POSTGRES_HOST} port={settings.POSTGRES_PORT} "
        f"user={settings.POSTGRES_USER} password={settings.POSTGRES_PASSWORD} "
        "dbname=postgres connect_timeout=2"
    )
    try:
        conn = psycopg.connect(dsn, autocommit=True)
    except Exception:
        pytest.skip("PostgreSQL is not available")
    with conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (settings.POSTGRES_DB,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{settings.POSTGRES_DB}"')

    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Async HTTP client bound to the ASGI app, with lifespan managed."""
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as async_client:
            yield async_client
