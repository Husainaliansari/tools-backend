#!/usr/bin/env bash
# Run the test suite with coverage.
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${APP_ENV:-testing}"
exec pytest --cov=app --cov-report=term-missing "$@"
