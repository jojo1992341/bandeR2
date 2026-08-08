#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PYTHON="$SCRIPT_DIR/../.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

echo "=== Rollback rapide vers la version précédente en recette (§19.3) ==="
"$PYTHON" "$SCRIPT_DIR/rollback_recette.py"
echo "=== Rollback terminé avec succès ==="
