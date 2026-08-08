#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(dirname "$SCRIPT_DIR")
if [ -d "$REPO_ROOT/.venv/bin" ]; then
    export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

echo "==> Running Python dependency scan (pip-audit — §15.7)..."
pip-audit -r backend/requirements.txt --no-deps

echo "==> Running performance budgets check (§17.3, §17.5)..."
python3 ci/check_performance_budgets.py

echo "==> Running OWASP Top 10, Performance SLOs & Integration Tests (§15.7, §17.1)..."
PYTHONPATH=backend pytest backend/tests/ -v
