#!/usr/bin/env bash
# Run the same checks as GitHub Actions locally.
# Usage: bash scripts/run-ci.sh

set -euo pipefail

echo "=== ruff check ==="
ruff check src/ tests/

echo "=== ruff format check ==="
ruff format --check src/ tests/

echo "=== mypy ==="
mypy src/

echo "=== pytest ==="
pytest tests/ -v --cov=ai_spend --cov-report=term-missing

echo "=== All checks passed ==="
