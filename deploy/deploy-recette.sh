#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PYTHON="$SCRIPT_DIR/../.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

echo "=== Déploiement automatique en recette RythmoAI v2 (§19.3) ==="
"$PYTHON" "$SCRIPT_DIR/package_release.py"
"$PYTHON" "$SCRIPT_DIR/deploy_recette.py"
echo "=== Déploiement recette terminé avec succès ==="
