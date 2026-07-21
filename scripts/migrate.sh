#!/usr/bin/env bash
# Apply database migrations to the latest revision.
set -euo pipefail
cd "$(dirname "$0")/.."
exec alembic upgrade head
