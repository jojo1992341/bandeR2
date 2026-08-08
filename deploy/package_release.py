#!/usr/bin/env python3
"""
Packaging de l'artefact de livraison en archive .zip versionnée (§19.2, §19.3) :
Contient le code backend, les assets frontend buildés, les scripts .bat/.ps1
et les fichiers de configuration par défaut.
"""

import os
import shutil
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

DEFAULT_RELEASES_DIR = Path("deploy/releases")


def package_delivery_artifact(
    version: str = "2.0.0",
    output_dir: Path = DEFAULT_RELEASES_DIR,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_filename = f"rythmoai-release-{version}-{timestamp}.zip"
    zip_path = output_dir / zip_filename

    # Sauvegarder l'ancienne version latest en tant que previous pour rollback rapide (§19.3)
    latest_path = output_dir / "rythmoai-release-latest.zip"
    previous_path = output_dir / "rythmoai-release-previous.zip"
    if latest_path.exists():
        try:
            shutil.copy2(latest_path, previous_path)
        except Exception:
            pass

    # Fichiers et dossiers à inclure dans l'archive de livraison (§19.2)
    dirs_to_include = [
        "backend/app",
        "backend/alembic",
        "frontend/src",
        "frontend/dist",
        "deploy/nginx",
    ]
    files_to_include = [
        "backend/requirements.txt",
        "backend/alembic.ini",
        "install.ps1",
        "install.bat",
        "start.ps1",
        "start.bat",
        "stop.ps1",
        "stop.bat",
        "install-service.ps1",
        "install-service.bat",
        "backup.ps1",
        "restore.ps1",
        "schedule-backup.ps1",
    ]

    files_added = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Ajout des fichiers racines et backend/config
        for rel_path in files_to_include:
            full_path = repo_root / rel_path
            if full_path.exists() and full_path.is_file():
                zf.write(full_path, arcname=rel_path)
                files_added += 1

        # Ajout des dossiers complets
        for rel_dir in dirs_to_include:
            full_dir = repo_root / rel_dir
            if not full_dir.exists():
                continue
            for root, dirs, files in os.walk(full_dir):
                for f in files:
                    if f.endswith(
                        (".pyc", ".pyo", ".log", ".tmp", ".swp")
                    ) or "__pycache__" in root:
                        continue
                    file_path = Path(root) / f
                    arcname = os.path.relpath(file_path, repo_root)
                    zf.write(file_path, arcname=arcname)
                    files_added += 1

    # Mettre à jour latest
    try:
        shutil.copy2(zip_path, latest_path)
    except Exception:
        pass

    return {
        "status": "success",
        "archive_path": str(zip_path),
        "archive_size_bytes": zip_path.stat().st_size,
        "files_included": files_added,
        "version": version,
        "previous_archive": (
            str(previous_path) if previous_path.exists() else None
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    res = package_delivery_artifact()
    print("=== RythmoAI Delivery Artifact Packaged (§19.2, §19.3) ===")
    print(f"Archive  : {res['archive_path']}")
    print(f"Size     : {res['archive_size_bytes']} bytes")
    print(f"Files    : {res['files_included']}")
    print(f"Previous : {res['previous_archive']}")


if __name__ == "__main__":
    main()
