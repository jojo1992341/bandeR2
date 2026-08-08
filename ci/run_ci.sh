#!/usr/bin/env bash
set -euo pipefail

echo "==> Running Python dependency scan (pip-audit — §15.7)..."
pip-audit -r backend/requirements.txt --no-deps

echo "==> Running OWASP Top 10 systematic review & Integration Tests (§15.7)..."
PYTHONPATH=backend pytest backend/tests/ -v
