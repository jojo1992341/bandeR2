#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PYTHON="$SCRIPT_DIR/.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

BACKUP_FILE="${1:-}"

echo "=== Restauration PRA/PCA RythmoAI v2 (§18.7) ==="
PYTHONPATH=backend "$PYTHON" -c "
import sys, json, os
from pathlib import Path
from app.core.database import SessionLocal
from app.core.backup_service import restore_from_backup, DEFAULT_BACKUP_DIR

backup_arg = '$BACKUP_FILE'
backup_path = None
if backup_arg:
    backup_path = Path(backup_arg)
else:
    if DEFAULT_BACKUP_DIR.exists():
        files = sorted(DEFAULT_BACKUP_DIR.glob('rythmoai_backup_*.sql'), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            backup_path = files[0]

if not backup_path or not backup_path.exists():
    print('ERREUR: Fichier de sauvegarde introuvable', file=sys.stderr)
    sys.exit(1)

db = SessionLocal()
try:
    res = restore_from_backup(
        db,
        backup_file=backup_path,
        remote_media_dir=Path('backups/remote_storage')
    )
    print(json.dumps(res, indent=2))
finally:
    db.close()
"
echo "=== Restauration terminée avec succès : système fonctionnel ==="
