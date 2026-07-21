#!/usr/bin/env bash
# Run all static analysis checks (no modifications).
set -euo pipefail
cd "$(dirname "$0")/.."
echo "==> ruff (lint)"
ruff check app tests
echo "==> black (check)"
black --check app tests
echo "==> isort (check)"
isort --check-only app tests
echo "==> mypy"
mypy app
