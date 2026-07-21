# FastAPI Enterprise Backend

A production-ready **FastAPI** backend foundation built for long-term
maintainability and rapid, safe feature development. It ships with clean
architecture, layered separation of concerns, structured logging, centralized
error handling, async SQLAlchemy 2.x, Alembic migrations, Redis/Celery
configuration, and a full local + Linux deployment story.

> **Scope:** This repository is the *foundation* only. It contains no business
> logic, models, CRUD, or authentication — just a robust, well-structured base
> to build on.

---

## Table of contents

- [Project overview](#project-overview)
- [Tech stack](#tech-stack)
- [Folder structure](#folder-structure)
- [Architecture](#architecture)
- [Installation](#installation)
- [Environment variables](#environment-variables)
- [Running locally](#running-locally)
- [Database migrations](#database-migrations)
- [Code quality](#code-quality)
- [Testing](#testing)
- [Linux deployment guide](#linux-deployment-guide)
- [API documentation](#api-documentation)

---

## Project overview

The application is organized in layers with a strict, one-directional dependency
flow (`api → services → repositories → db`, with `core`, `config`, `schemas`,
and `exceptions` as shared foundations). This keeps the codebase testable,
replaceable, and easy to reason about as it grows.

Key characteristics:

- **Twelve-Factor configuration** via Pydantic Settings — everything from the
  environment, no hard-coded secrets, per-environment profiles.
- **Structured logging** (structlog) with automatic request/correlation ids,
  JSON in production and human-readable in development.
- **Centralized exception handling** producing a single, predictable error
  envelope for every failure.
- **Async database access** with SQLAlchemy 2.x + asyncpg and Alembic
  migrations wired to the app's settings.
- **Operational readiness**: health endpoint, security middleware, Gunicorn +
  Uvicorn worker config, systemd unit, and Nginx sample.

---

## Tech stack

| Concern            | Technology                                  |
| ------------------ | ------------------------------------------- |
| Language           | Python 3.13+                                |
| Web framework      | FastAPI                                     |
| Validation         | Pydantic v2 / pydantic-settings             |
| ORM                | SQLAlchemy 2.x (async, asyncpg)             |
| Migrations         | Alembic                                     |
| Database           | PostgreSQL                                  |
| Cache / broker     | Redis                                       |
| Background tasks   | Celery (configuration only)                 |
| Logging            | structlog                                   |
| ASGI server        | Uvicorn (dev) / Gunicorn + Uvicorn worker   |
| Reverse proxy      | Nginx                                       |
| Process manager    | systemd                                     |
| Testing            | pytest, pytest-asyncio, HTTPX               |
| Quality            | Ruff, Black, isort, mypy, pre-commit        |

---

## Folder structure

```
backend/
├── app/
│   ├── api/               # HTTP interface layer (routers, versioned endpoints)
│   │   ├── v1/            #   Version 1 of the public API
│   │   └── router.py      #   Top-level aggregator mounting versioned routers
│   ├── config/            # Pydantic settings: base + dev/prod + factory
│   ├── core/              # Cross-cutting primitives: context, lifespan
│   ├── db/                # Engine, session, declarative base, Redis config
│   ├── middleware/        # CORS, TrustedHost, GZip, request-id, logging, security
│   ├── dependencies/      # Reusable FastAPI DI providers (db, pagination, ...)
│   ├── exceptions/        # Exception hierarchy + centralized handlers
│   ├── logging/           # structlog + stdlib logging configuration
│   ├── schemas/           # Base schema + response envelopes + validators
│   ├── models/            # SQLAlchemy models (added per feature) — empty
│   ├── repositories/      # Data-access layer (added per feature) — empty
│   ├── services/          # Business/use-case layer (added per feature) — empty
│   ├── workers/           # Celery app + worker configuration
│   ├── tasks/             # Celery task modules (added per feature) — empty
│   ├── utils/             # Pure, stateless helpers — empty
│   ├── constants/         # Shared enums/constants (error codes, ...)
│   ├── common/            # Shared building blocks (pagination result, ...)
│   ├── health/            # Liveness endpoint
│   └── main.py            # Application factory + ASGI entrypoint (app.main:app)
├── migrations/            # Alembic environment + versioned migration scripts
├── tests/                 # Pytest suite (conftest + fixtures scaffold)
├── scripts/               # Dev/ops helper scripts
├── docs/deployment/       # systemd unit + Nginx sample
├── requirements/          # base / development / production dependency sets
├── .env.example           # Documented environment template
├── .pre-commit-config.yaml
├── .gitignore
├── pyproject.toml         # Tooling config (ruff/black/isort/mypy/pytest)
├── gunicorn.conf.py       # Production Gunicorn configuration
├── alembic.ini            # Alembic configuration (URL injected from settings)
└── README.md
```

### Why each layer exists

- **api** — Translates HTTP to/from the service layer. Versioned so breaking
  changes ship as `v2` without disrupting `v1` clients. Contains no business
  logic.
- **config** — Single source of truth for configuration, per environment.
- **core** — Framework-agnostic primitives many layers depend on (request
  context, application lifespan). Features depend on core, never the reverse.
- **db** — Owns database/Redis connectivity: engine, session factory, declarative
  base, connection pools. Nothing connects at import time.
- **middleware** — Cross-cutting request/response concerns assembled in one place.
- **dependencies** — Reusable DI providers keep endpoints thin and testable.
- **exceptions** — One place that guarantees a consistent error contract.
- **logging** — Consistent, structured, correlated logs across app and framework.
- **schemas** — Shared request/response contracts and the standard envelope.
- **models / repositories / services** — The classic Clean Architecture triad:
  persistence, data-access, and business logic, respectively. Empty by design.
- **workers / tasks** — Async processing infrastructure vs. task implementations.
- **utils / common / constants** — Pure helpers, shared building blocks, and
  shared constants (DRY).
- **health** — Operational endpoints decoupled from feature routes.

### How the structure supports scalability

New features slot into the existing layers without touching the foundation:
add a model (`models/`), a repository (`repositories/`), a service
(`services/`), request/response schemas (`schemas/`), and an endpoint module
under `api/v1/`, then register its router in `api/v1/router.py` and its model in
`db/base_registry.py`. Layers depend inward only, so features stay isolated and
independently testable, and the API can evolve by version without breaking
existing clients.

---

## Architecture

- **Clean Architecture** — dependencies point inward; the API layer depends on
  services, services on repositories, repositories on the database.
- **SOLID / DRY / KISS** — single-responsibility modules, shared constants and
  schemas, and deliberately simple wiring.
- **Separation of Concerns** — HTTP, business logic, and persistence never mix.
- **Twelve-Factor App** — config from the environment, stateless processes,
  logs to stdout, explicit dependencies.

---

## Installation

### Prerequisites

- Python **3.13+**
- PostgreSQL (running and reachable)
- Redis (required for Celery; optional otherwise)

### 1. Virtual environment

```bash
cd backend
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
# Development (includes tooling + test dependencies)
pip install -r requirements/development.txt

# Production (runtime only)
pip install -r requirements/production.txt
```

---

## Environment variables

Copy the template and edit values:

```bash
cp .env.example .env
```

Generate a strong secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

All variables are documented inline in [`.env.example`](.env.example). The
active profile is chosen by `APP_ENV` (`development` | `staging` |
`production` | `testing`).

---

## Running locally

### With Uvicorn (hot reload, development)

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# or:
./scripts/run_dev.sh
```

### With Gunicorn (production-like)

```bash
gunicorn app.main:app -c gunicorn.conf.py
# or:
./scripts/run_prod.sh
```

Verify the service is up:

```bash
curl http://localhost:8000/health
# {"status":"healthy"}
```

---

## Database migrations

Alembic reads the database URL from application settings (no secrets in
`alembic.ini`) and diffs against `app.db.base_registry.Base.metadata`.

```bash
# Create a new autogenerated revision (after adding/altering models)
alembic revision --autogenerate -m "describe change"

# Apply migrations to latest
alembic upgrade head
# or:
./scripts/migrate.sh

# Roll back one revision
alembic downgrade -1

# Show current / history
alembic current
alembic history
```

> Remember to import new model modules in `app/db/base_registry.py` so Alembic
> can see them during autogeneration.

---

## Code quality

```bash
# Auto-format
./scripts/format.sh          # ruff --fix + isort + black

# Static checks (no changes)
./scripts/lint.sh            # ruff + black --check + isort --check + mypy

# Individually
ruff check app tests
black app tests
isort app tests
mypy app
```

### Pre-commit

```bash
pre-commit install           # install the git hook (run once)
pre-commit run --all-files   # run all hooks against the whole repo
```

---

## Testing

```bash
pytest
# with coverage:
./scripts/test.sh
```

The suite uses `pytest-asyncio` (auto mode) and an HTTPX `AsyncClient` bound to
the ASGI app with lifespan handling (see `tests/conftest.py`). No tests are
included in the foundation — only the harness and fixtures scaffold.

---

## Linux deployment guide

Target stack: **Gunicorn + Uvicorn worker + Nginx + systemd** on Ubuntu/Linux.

### 1. System packages

```bash
sudo apt update
sudo apt install -y python3.13 python3.13-venv nginx
```

### 2. Deploy the code

```bash
sudo mkdir -p /opt/fastapi-backend
sudo chown "$USER" /opt/fastapi-backend
# copy/clone the project so it lives at /opt/fastapi-backend/backend
cd /opt/fastapi-backend/backend
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements/production.txt
```

### 3. Configure

```bash
cp .env.example .env
# edit .env: set APP_ENV=production, a strong SECRET_KEY, real ALLOWED_HOSTS,
# CORS_ORIGINS, and PostgreSQL/Redis connection details.
alembic upgrade head
```

### 4. systemd service

```bash
sudo cp docs/deployment/fastapi-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fastapi-backend
sudo systemctl status fastapi-backend
```

### 5. Nginx reverse proxy

```bash
sudo cp docs/deployment/nginx.conf.sample /etc/nginx/sites-available/fastapi-backend
sudo ln -s /etc/nginx/sites-available/fastapi-backend /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

For TLS, terminate HTTPS at Nginx (e.g. Certbot) and redirect HTTP → HTTPS.

### Celery worker & Beat scheduler

PDF-tool tasks run on the `pdf` queue; the cleanup scheduler runs on
`maintenance`. On Windows dev boxes add `--pool=solo`.

```bash
# Worker consuming all queues
celery -A app.workers.celery_app.celery_app worker -Q default,pdf,maintenance --loglevel=info

# Beat scheduler (drives the periodic cleanup of expired files/jobs/temp)
celery -A app.workers.celery_app.celery_app beat --loglevel=info
```

### External tool binaries

Conversions shell out to system binaries, each configurable via settings
(quoted absolute paths work on Windows):

| Setting          | Binary      | Used by                                  |
|------------------|-------------|------------------------------------------|
| `SOFFICE_BIN`    | LibreOffice | Word/Excel/PPT → PDF                     |
| `UNOCONVERT_BIN` | unoserver   | external unoserver (overrides `OFFICE_ENGINE`) |
| `PDFTOPPM_BIN`   | Poppler     | PDF → JPG/PNG, thumbnails                |
| `GHOSTSCRIPT_BIN`| Ghostscript | Compress, Compress Scanned               |
| `OCRMYPDF_BIN`   | OCRmyPDF    | OCR                                      |

A missing binary fails the affected job with a clear message; the API and all
pure-Python tools (merge/split/watermark/protect/redact/forms/repair/…) keep
working. Repair uses libqpdf in-process (bundled with pikepdf), so it needs no
external binary.

### Fast Office conversions (managed unoserver pool)

Office → PDF conversions (`ppt-to-pdf`, `word-to-pdf`, `excel-to-pdf`) support
three engines, selected by `OFFICE_ENGINE` (default `auto`):

- **Managed unoserver pool** — each worker process keeps
  `UNOSERVER_POOL_SIZE` LibreOffice instances alive and converts on them
  directly. Skips the 1.5–3 s soffice startup per document (~5–10× more
  throughput under load), heals crashed instances automatically, and
  multi-file jobs convert in parallel across the pool.
- **Per-conversion soffice** — the zero-dependency fallback used by `auto`
  when unoserver cannot run; warm profile pool, retry on corrupt profile.
- **External unoserver** (`UNOCONVERT_BIN`) — you run and supervise
  `unoserver` yourself; the app is only a client.

Enabling the pool:

```bash
# Windows (local dev): nothing else needed — the pool runs the package under
# LibreOffice's bundled python.exe, discovered next to SOFFICE_BIN.
pip install unoserver

# Linux (production): unoserver's server half needs the python-uno bridge.
sudo apt install -y libreoffice-impress libreoffice-calc libreoffice-writer \
                    python3-uno fonts-liberation fonts-noto
pip install unoserver          # into the venv (create it with
                               # --system-site-packages so `uno` is importable),
                               # or install unoserver system-wide
```

`auto` probes at startup and logs the outcome (`unoserver_pool_active` /
`unoserver_pool_unavailable`); set `OFFICE_ENGINE=unoserver` in production to
fail loudly instead of silently degrading to the slow path. Install a real
font set on Linux servers — LibreOffice silently substitutes missing fonts
and slide layouts shift.

Self-healing: a conversion that crashes its LibreOffice instance falls back
to soffice for that file, and repeated crashes disable the pool for the
process (`unoserver_pool_disabled` in the logs). Some LibreOffice builds —
portable Windows installs especially — cannot run reliably under UNO control
at all; on such machines set `OFFICE_ENGINE=soffice` and skip the probing.

### Production checklist

- Set a strong `SECRET_KEY` (JWTs are signed with it) and explicit
  `CORS_ORIGINS` / `ALLOWED_HOSTS`.
- Run `alembic upgrade head` on deploy (two migrations: core tables, users).
- Redis powers the broker, upload rate limiting (fail-open) and WebSocket
  progress push (falls back to DB polling without it).
- Job progress: `WS /api/v1/jobs/{id}/ws` (push) with `GET .../events` (SSE)
  and plain polling as fallbacks — clients degrade automatically.
- License note: `pdf2docx` (PDF→Word) and the Redact tool depend on PyMuPDF
  (AGPL) — review before commercial distribution.

### Local storage layout

Created automatically at startup under `STORAGE_ROOT` (default `./storage`):

```
storage/
├── uploads/      # raw user uploads      (uploads/YYYY/MM/DD/<uuid>.<ext>)
├── processed/    # tool outputs          (same sharding)
├── temp/         # per-job scratch workspaces (auto-removed)
├── thumbnails/   # preview images
└── logs/         # rotating JSON application logs
```

Uploads and outputs expire after `FILE_RETENTION_HOURS` (default 24h); the
Beat-scheduled `maintenance.cleanup_expired` task purges them every
`CLEANUP_INTERVAL_MINUTES`.

---

## API documentation

When the server is running, interactive docs are available at:

- **Swagger UI** — `/docs`
- **ReDoc** — `/redoc`
- **OpenAPI schema** — `/openapi.json`

These paths are configurable (and can be disabled in production) via the
`DOCS_URL`, `REDOC_URL`, and `OPENAPI_URL` settings.
```
