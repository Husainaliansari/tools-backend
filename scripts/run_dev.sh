#!/usr/bin/env bash
# Run the app locally with hot-reload (development only).
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${APP_ENV:-development}"
exec uvicorn app.main:app --reload --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
