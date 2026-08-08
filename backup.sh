#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PYTHON="$SCRIPT_DIR/.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

echo "=== Sauvegarde automatique quotidienne RythmoAI v2 (§18.7) ==="
PYTHONPATH=backend "$PYTHON" -c "
import json
from pathlib import Path
from app.core.database import SessionLocal
from app.core.backup_service import create_daily_backup

db = SessionLocal()
try:
    res = create_daily_backup(
        db,
        backup_dir=Path('backups/db'),
        remote_media_dir=Path('backups/remote_storage'),
        retention_days=30
    )
    print(json.dumps(res, indent=2))
finally:
    db.close()
"
echo "=== Sauvegarde terminée avec succès ==="
