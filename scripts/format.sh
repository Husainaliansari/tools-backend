#!/usr/bin/env bash
# Auto-format the codebase.
set -euo pipefail
cd "$(dirname "$0")/.."
ruff check --fix app tests
isort app tests
black app tests
