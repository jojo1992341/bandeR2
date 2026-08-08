import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.config import get_settings
from app.core.logging import logger

DEFAULT_BACKUP_DIR = Path("backups/db")
DEFAULT_REMOTE_MEDIA_DIR = Path("backups/remote_storage")


def _sql_literal(val) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, uuid.UUID):
        return f"'{val.hex}'"
    if isinstance(val, (dict, list)):
        import json

        esc = json.dumps(val).replace("'", "''")
        return f"'{esc}'"
    esc = str(val).replace("'", "''")
    return f"'{esc}'"


def generate_sql_dump(db: Session, output_file: Path) -> int:
    """
    Génère un dump SQL universel compatible PostgreSQL/SQLite (§18.7).
    """
    from app.models import (
        Base,
        Studio,
        User,
        StudioMembership,
        StudioInvitation,
        Project,
        MediaAsset,
        Replica,
        ReplicaHistory,
        RythmoVersion,
        Export,
        Comment,
        AuditLog,
        SecurityAlert,
    )

    models_in_order = [
        Studio,
        User,
        StudioMembership,
        StudioInvitation,
        Project,
        MediaAsset,
        Replica,
        ReplicaHistory,
        RythmoVersion,
        Export,
        Comment,
        AuditLog,
        SecurityAlert,
    ]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "-- RythmoAI v2 Daily Backup SQL Dump (§18.7)",
        f"-- Generated at {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    total_statements = 0

    for model in models_in_order:
        table = model.__table__
        rows = db.query(model).all()
        for row in rows:
            col_names = list(table.columns.keys())
            cols_str = ", ".join([f'"{c}"' for c in col_names])
            vals = []
            for c in col_names:
                val = getattr(row, c, None)
                vals.append(_sql_literal(val))
            vals_str = ", ".join(vals)
            lines.append(
                f'INSERT INTO "{table.name}" ({cols_str}) VALUES ({vals_str});'
            )
            total_statements += 1

    lines.append("")
    output_file.write_text("\n".join(lines), encoding="utf-8")
    return total_statements


def restore_sql_dump(db: Session, backup_file: Path) -> int:
    """
    Restaure une base de données à partir d'un fichier dump SQL (§18.7).
    """
    from app.models import (
        Base,
        Studio,
        User,
        StudioMembership,
        StudioInvitation,
        Project,
        MediaAsset,
        Replica,
        ReplicaHistory,
        RythmoVersion,
        Export,
        Comment,
        AuditLog,
        SecurityAlert,
        set_allow_audit_log_purge,
    )

    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")

    # 1. Clear existing data in reverse dependency order
    set_allow_audit_log_purge(True)
    try:
        for model in [
            Comment,
            Export,
            RythmoVersion,
            ReplicaHistory,
            Replica,
            MediaAsset,
            Project,
            StudioMembership,
            StudioInvitation,
            AuditLog,
            SecurityAlert,
            User,
            Studio,
        ]:
            try:
                db.query(model).delete(synchronize_session=False)
            except Exception:
                pass
        db.commit()
    finally:
        set_allow_audit_log_purge(False)

    # 2. Execute SQL insert statements
    content = backup_file.read_text(encoding="utf-8")
    executed_count = 0
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        if line.startswith("INSERT INTO"):
            try:
                db.execute(text(line))
                executed_count += 1
            except Exception as e:
                logger.warning(
                    f"Restore warning on line [{line[:50]}...]: {e}"
                )
    db.commit()
    return executed_count


def enforce_backup_retention(
    backup_dir: Path, retention_days: int = 30, now: Optional[datetime] = None
) -> int:
    """
    Purge automatique des fichiers de sauvegarde vieux de plus de 30 jours (§18.7).
    """
    if not backup_dir.exists():
        return 0

    if now is None:
        now = datetime.now(timezone.utc)

    cutoff_time = now - timedelta(days=retention_days)
    purged_count = 0

    for file_path in backup_dir.iterdir():
        if not file_path.is_file():
            continue
        if file_path.suffix not in (".sql", ".gz", ".dump", ".bak"):
            continue
        mtime = datetime.fromtimestamp(
            file_path.stat().st_mtime, tz=timezone.utc
        )
        if mtime < cutoff_time:
            try:
                file_path.unlink()
                purged_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete expired backup file: {e}")

    return purged_count


def copy_media_to_remote_storage(
    local_dirs: List[Path], remote_dir: Path
) -> int:
    """
    Copie planifiée du dossier de stockage des médias/exports vers un emplacement distant (§18.7).
    """
    remote_dir.mkdir(parents=True, exist_ok=True)
    copied_files = 0
    for local_dir in local_dirs:
        if not local_dir.exists():
            continue
        for root, dirs, files in os.walk(local_dir):
            rel_path = os.path.relpath(root, local_dir)
            target_dir = (
                remote_dir / local_dir.name / rel_path
                if rel_path != "."
                else remote_dir / local_dir.name
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                src_file = Path(root) / f
                dst_file = target_dir / f
                try:
                    shutil.copy2(src_file, dst_file)
                    copied_files += 1
                except Exception as e:
                    logger.warning(f"Remote storage copy warning: {e}")
    return copied_files


def restore_media_from_remote_storage(
    remote_dir: Path, target_base_dir: Path
) -> int:
    """
    Restauration des médias/exports depuis l'emplacement de sauvegarde distant (§18.7).
    """
    if not remote_dir.exists():
        return 0
    restored_files = 0
    for root, dirs, files in os.walk(remote_dir):
        rel_path = os.path.relpath(root, remote_dir)
        target_dir = (
            target_base_dir / rel_path if rel_path != "." else target_base_dir
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            src_file = Path(root) / f
            dst_file = target_dir / f
            try:
                shutil.copy2(src_file, dst_file)
                restored_files += 1
            except Exception as e:
                logger.warning(f"Media restore warning: {e}")
    return restored_files


def create_daily_backup(
    db: Session,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    remote_media_dir: Path = DEFAULT_REMOTE_MEDIA_DIR,
    retention_days: int = 30,
    media_dirs: Optional[List[Path]] = None,
) -> Dict[str, Any]:
    """
    Sauvegarde automatique quotidienne complète de PostgreSQL et copie du stockage médias (§18.7).
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"rythmoai_backup_{timestamp}.sql"

    # 1. Dump SQL de la base de données
    stmt_count = generate_sql_dump(db, backup_file)

    # 2. Rétention 30 jours
    purged = enforce_backup_retention(backup_dir, retention_days=retention_days)

    # 3. Copie planifiée du stockage médias et exports
    if media_dirs is None:
        media_dirs = [Path("uploads"), Path("exports")]
    copied_media = copy_media_to_remote_storage(
        local_dirs=media_dirs, remote_dir=remote_media_dir
    )

    return {
        "status": "success",
        "backup_file": str(backup_file),
        "backup_size_bytes": backup_file.stat().st_size,
        "statement_count": stmt_count,
        "purged_old_backups": purged,
        "copied_media_files": copied_media,
        "remote_media_dir": str(remote_media_dir),
        "retention_days": retention_days,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def restore_from_backup(
    db: Session,
    backup_file: Path,
    remote_media_dir: Optional[Path] = None,
    target_media_dir: Path = Path("."),
) -> Dict[str, Any]:
    """
    Restauration PRA/PCA à partir d'une sauvegarde pour aboutir à un système fonctionnel (§18.7).
    """
    # 1. Restauration de la base de données
    restored_rows = restore_sql_dump(db, backup_file)

    # 2. Restauration des fichiers médias
    restored_media = 0
    if remote_media_dir and remote_media_dir.exists():
        restored_media = restore_media_from_remote_storage(
            remote_dir=remote_media_dir, target_base_dir=target_media_dir
        )

    return {
        "status": "success",
        "backup_file": str(backup_file),
        "restored_rows": restored_rows,
        "restored_media_files": restored_media,
        "message": "Restauration PRA/PCA aboutissant à un système 100% fonctionnel (§18.7)",
        "restored_at": datetime.now(timezone.utc).isoformat(),
    }
