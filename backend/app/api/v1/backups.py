import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.rbac import get_current_user_payload
from app.core.backup_service import (
    create_daily_backup,
    restore_from_backup,
    enforce_backup_retention,
    DEFAULT_BACKUP_DIR,
    DEFAULT_REMOTE_MEDIA_DIR,
)

router = APIRouter()


class BackupCreateIn(BaseModel):
    retention_days: int = 30
    remote_dir: Optional[str] = None


class BackupRestoreIn(BaseModel):
    backup_file: Optional[str] = None
    remote_dir: Optional[str] = None


@router.post("/backups", status_code=status.HTTP_201_CREATED)
@router.post("/api/v1/backups", status_code=status.HTTP_201_CREATED)
def trigger_backup(
    data: BackupCreateIn = BackupCreateIn(),
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    remote_dir = (
        Path(data.remote_dir)
        if data.remote_dir
        else DEFAULT_REMOTE_MEDIA_DIR
    )
    res = create_daily_backup(
        db,
        backup_dir=DEFAULT_BACKUP_DIR,
        remote_media_dir=remote_dir,
        retention_days=data.retention_days,
    )
    return res


@router.post("/backups/restore")
@router.post("/api/v1/backups/restore")
def trigger_restore(
    data: BackupRestoreIn = BackupRestoreIn(),
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    backup_path = None
    if data.backup_file:
        backup_path = Path(data.backup_file)
    else:
        # Trouver la sauvegarde la plus récente
        if DEFAULT_BACKUP_DIR.exists():
            files = sorted(
                DEFAULT_BACKUP_DIR.glob("rythmoai_backup_*.sql"),
                key=os.path.getmtime,
                reverse=True,
            )
            if files:
                backup_path = files[0]

    if not backup_path or not backup_path.exists():
        raise HTTPException(
            status_code=404, detail="Fichier de sauvegarde non trouvé"
        )

    remote_dir = (
        Path(data.remote_dir)
        if data.remote_dir
        else DEFAULT_REMOTE_MEDIA_DIR
    )
    res = restore_from_backup(
        db, backup_file=backup_path, remote_media_dir=remote_dir
    )
    return res


@router.post("/backups/prune")
@router.post("/api/v1/backups/prune")
def trigger_retention_prune(
    data: BackupCreateIn = BackupCreateIn(),
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    count = enforce_backup_retention(
        DEFAULT_BACKUP_DIR, retention_days=data.retention_days
    )
    return {
        "status": "success",
        "purged_old_backups": count,
        "retention_days": data.retention_days,
    }
