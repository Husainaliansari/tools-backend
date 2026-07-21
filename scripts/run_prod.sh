#!/usr/bin/env bash
# Run the app under Gunicorn with Uvicorn workers (production).
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${APP_ENV:-production}"
exec gunicorn app.main:app -c gunicorn.conf.py
