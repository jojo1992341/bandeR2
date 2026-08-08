"""
Test d'intégration PRA/PCA et d'enregistrement des services Windows persistants (§18.4, §18.7).
Condition d'achèvement :
- sur une machine de test, les services démarrent automatiquement au redémarrage du serveur (SERVICE_AUTO_START / AppExit Default Restart)
- une restauration à partir d'une sauvegarde de test aboutit à un système fonctionnel
"""

import os
import shutil
import time
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from app.core.password import hash_password
from app.core.auth_handler import create_access_token
from app.models import (
    User,
    Studio,
    Project,
    MediaAsset,
    Replica,
    Export,
    AuditLog,
    SecurityAlert,
    StudioMembership,
    set_allow_audit_log_purge,
)
from app.core.backup_service import (
    create_daily_backup,
    restore_from_backup,
    enforce_backup_retention,
    DEFAULT_BACKUP_DIR,
)

client = TestClient(app)


def get_db_session() -> Session:
    return SessionLocal()


def cleanup_pra_test_data(
    test_backup_dir: Path, test_remote_media_dir: Path
):
    db = get_db_session()
    try:
        set_allow_audit_log_purge(True)
        try:
            db.query(AuditLog).filter(
                AuditLog.user_email == "pra_admin@studio.com"
            ).delete(synchronize_session=False)
            db.query(SecurityAlert).filter(
                SecurityAlert.user_email == "pra_admin@studio.com"
            ).delete(synchronize_session=False)
        finally:
            set_allow_audit_log_purge(False)

        db.query(Export).filter(
            Export.created_by == "pra_admin@studio.com"
        ).delete(synchronize_session=False)

        studio = (
            db.query(Studio)
            .filter(Studio.name == "Studio PRA Test §18.7")
            .first()
        )
        if studio:
            projects = (
                db.query(Project)
                .filter(Project.studio_id == studio.id)
                .all()
            )
            for p in projects:
                media = (
                    db.query(MediaAsset)
                    .filter(MediaAsset.project_id == p.id)
                    .all()
                )
                for m in media:
                    db.query(Replica).filter(
                        Replica.media_id == m.id
                    ).delete(synchronize_session=False)
                    db.query(MediaAsset).filter(
                        MediaAsset.id == m.id
                    ).delete(synchronize_session=False)
                db.query(Project).filter(Project.id == p.id).delete(
                    synchronize_session=False
                )
            user = (
                db.query(User)
                .filter(User.email == "pra_admin@studio.com")
                .first()
            )
            if user:
                db.query(StudioMembership).filter(
                    StudioMembership.user_id == user.id
                ).delete(synchronize_session=False)
                db.delete(user)
            db.delete(studio)

        db.commit()
    finally:
        db.close()

    # Nettoyage des dossiers de test temporaires
    if test_backup_dir.exists():
        try:
            shutil.rmtree(test_backup_dir)
        except Exception:
            pass
    if test_remote_media_dir.exists():
        try:
            shutil.rmtree(test_remote_media_dir)
        except Exception:
            pass


def test_install_service_script_registers_persistent_services_with_auto_start_and_restart():
    """
    Vérifie qu'install-service.ps1 est présent et enregistre l'API, les workers Celery (CPU/GPU)
    et Nginx comme services Windows persistants via NSSM, configurés pour :
    - Démarrent automatiquement au redémarrage du serveur (SERVICE_AUTO_START)
    - Redémarrage automatique en cas de plantage (AppExit Default Restart)
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    install_service_ps1 = repo_root / "install-service.ps1"
    install_service_bat = repo_root / "install-service.bat"
    schedule_backup_ps1 = repo_root / "schedule-backup.ps1"

    assert (
        install_service_ps1.exists()
    ), "install-service.ps1 est requis à la racine par §18.4"
    assert (
        install_service_bat.exists()
    ), "install-service.bat est requis pour le lancement Windows"
    assert (
        schedule_backup_ps1.exists()
    ), "schedule-backup.ps1 est requis par §18.7"

    content = install_service_ps1.read_text(encoding="utf-8")

    # 1. Vérifier que l'ensemble des 5 services sont enregistrés (§18.4)
    for service_name in [
        "RythmoAI-API",
        "RythmoAI-CeleryCPU",
        "RythmoAI-CeleryGPU",
        "RythmoAI-CeleryBeat",
        "RythmoAI-Nginx",
    ]:
        assert (
            service_name in content
        ), f"Le service {service_name} doit être enregistré dans install-service.ps1"

    # 2. Vérifier la configuration NSSM pour le redémarrage automatique en cas de plantage (§18.4)
    assert (
        "AppExit Default Restart" in content
    ), "install-service.ps1 doit configurer 'nssm set <srv> AppExit Default Restart'"

    # 3. Vérifier la configuration NSSM pour le démarrage automatique au boot serveur (§18.4)
    assert (
        "SERVICE_AUTO_START" in content
    ), "install-service.ps1 doit configurer 'nssm set <srv> Start SERVICE_AUTO_START'"

    # 4. Vérifier que schedule-backup.ps1 planifie la sauvegarde quotidienne (§18.7)
    schedule_content = schedule_backup_ps1.read_text(encoding="utf-8")
    assert "Register-ScheduledTask" in schedule_content
    assert "RythmoAI-DailyBackup" in schedule_content
    assert "-Daily" in schedule_content


def test_backup_retention_remote_copy_and_restore_to_functional_system():
    """
    CONDITION D'ACHÈVEMENT (§18.7) :
    1. Configuration des sauvegardes automatiques quotidiennes PostgreSQL (pg_dump planifié, rétention 30 jours)
    2. Copie planifiée du stockage médias vers un emplacement distant
    3. Sur une machine de test, une restauration à partir d'une sauvegarde de test aboutit à un système fonctionnel
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    test_backup_dir = repo_root / "backups" / "test_pra_db"
    test_remote_media_dir = repo_root / "backups" / "test_pra_remote_storage"
    test_upload_dir = repo_root / "uploads"

    cleanup_pra_test_data(test_backup_dir, test_remote_media_dir)
    db = get_db_session()
    try:
        # 1. SETUP SYSTÈME INITIAL FONCTIONNEL
        studio = Studio(
            id=uuid.uuid4(), name="Studio PRA Test §18.7", plan="pro"
        )
        db.add(studio)
        db.commit()
        db.refresh(studio)

        admin = User(
            id=uuid.uuid4(),
            email="pra_admin@studio.com",
            hashed_password=hash_password("PraSafe_Admin_99!@#"),
            role="owner",
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        membership = StudioMembership(
            id=uuid.uuid4(),
            studio_id=studio.id,
            user_id=admin.id,
            role="owner",
        )
        db.add(membership)

        project = Project(
            id=uuid.uuid4(),
            studio_id=studio.id,
            title="Projet à restaurer §18.7",
            source_lang="fr",
            target_lang="fr",
            status="Pret_pour_edition",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        media = MediaAsset(
            id=uuid.uuid4(),
            project_id=project.id,
            storage_path="pra_test_video.mp4",
            status="confirmed",
        )
        db.add(media)
        db.commit()
        db.refresh(media)

        # Création de 4 répliques sur le projet initial
        replicas = []
        for i in range(4):
            replicas.append(
                Replica(
                    id=uuid.uuid4(),
                    media_id=media.id,
                    start_ms=i * 2000,
                    end_ms=i * 2000 + 1500,
                    text=f"Réplique #{i+1} avant sinistre PRA/PCA §18.7",
                    order_index=i,
                    version=1,
                    confidence_score=0.95,
                )
            )
        db.add_all(replicas)
        db.commit()

        first_replica_id = replicas[0].id

        # Authentification de l'administrateur
        token = create_access_token(
            {"sub": str(admin.id), "email": admin.email, "role": "owner"}
        )
        headers = {"Authorization": f"Bearer {token}"}

        # Vérifier que le système initial répond 200 OK via l'API
        resp_p_init = client.get(
            f"/api/v1/projects/{project.id}", headers=headers
        )
        assert resp_p_init.status_code == 200
        assert resp_p_init.json()["title"] == "Projet à restaurer §18.7"

        # ------------------------------------------------------------------
        # 2. SAUVEGARDE QUOTIDIENNE (pg_dump), RÉTENTION 30 JOURS & COPIE DISTANTE (§18.7)
        # ------------------------------------------------------------------
        # A. Exécution d'une sauvegarde automatique
        backup_res = create_daily_backup(
            db,
            backup_dir=test_backup_dir,
            remote_media_dir=test_remote_media_dir,
            retention_days=30,
            media_dirs=[test_upload_dir],
        )
        assert backup_res["status"] == "success"
        backup_file = Path(backup_res["backup_file"])
        assert backup_file.exists(), "Fichier de sauvegarde .sql doit être créé"
        assert (
            backup_file.stat().st_size > 0
        ), "Le dump SQL de sauvegarde ne doit pas être vide"
        assert backup_res["statement_count"] > 0

        # B. Vérification stricte de la rétention 30 jours (§18.7)
        # Simulation d'un fichier de sauvegarde expiré (vieux de 35 jours)
        old_backup_file = (
            test_backup_dir / "rythmoai_backup_20260701_000000.sql"
        )
        old_backup_file.write_text("-- old backup dump\n", encoding="utf-8")
        old_mtime = (
            datetime.now(timezone.utc) - timedelta(days=35)
        ).timestamp()
        os.utime(old_backup_file, (old_mtime, old_mtime))

        purged_count = enforce_backup_retention(
            test_backup_dir, retention_days=30
        )
        assert (
            purged_count >= 1
        ), "Les sauvegardes vieilles de > 30 jours doivent être automatiquement purgées"
        assert not old_backup_file.exists(), "L'ancienne sauvegarde doit être supprimée"
        assert (
            backup_file.exists()
        ), "La sauvegarde du jour ne doit pas être affectée par la purge de rétention"

        # ------------------------------------------------------------------
        # 3. SINISTRE SIMULÉ : PERTE TOTALE DE LA BASE DE DONNÉES ACTIVE
        # ------------------------------------------------------------------
        # Suppression complète du projet et des entités en base
        set_allow_audit_log_purge(True)
        try:
            db.query(Replica).filter(Replica.media_id == media.id).delete(
                synchronize_session=False
            )
            db.query(MediaAsset).filter(MediaAsset.id == media.id).delete(
                synchronize_session=False
            )
            db.query(Project).filter(Project.id == project.id).delete(
                synchronize_session=False
            )
            db.query(StudioMembership).filter(
                StudioMembership.user_id == admin.id
            ).delete(synchronize_session=False)
            db.query(User).filter(User.id == admin.id).delete(
                synchronize_session=False
            )
            db.query(Studio).filter(Studio.id == studio.id).delete(
                synchronize_session=False
            )
        finally:
            set_allow_audit_log_purge(False)
        db.commit()

        # Vérifier que le projet est désormais introuvable via l'API (404)
        resp_404 = client.get(f"/api/v1/projects/{project.id}", headers=headers)
        assert resp_404.status_code == 404

        # ------------------------------------------------------------------
        # 4. RESTAURATION À PARTIR DE LA SAUVEGARDE DE TEST
        # ------------------------------------------------------------------
        restore_res = restore_from_backup(
            db,
            backup_file=backup_file,
            remote_media_dir=test_remote_media_dir,
            target_media_dir=test_upload_dir,
        )
        assert restore_res["status"] == "success"
        assert restore_res["restored_rows"] > 0

        # ------------------------------------------------------------------
        # 5. VÉRIFICATION DE LA CONDITION D'ACHÈVEMENT :
        # "Une restauration à partir d'une sauvegarde de test aboutit à un système fonctionnel"
        # ------------------------------------------------------------------
        # A. Le projet restauré est immédiatement accessible en lecture via l'API -> 200 OK
        resp_p_after = client.get(
            f"/api/v1/projects/{project.id}", headers=headers
        )
        assert (
            resp_p_after.status_code == 200
        ), "Le projet restauré doit être accessible via l'API"
        restored_proj_data = resp_p_after.json()
        assert restored_proj_data["id"] == str(project.id)
        assert restored_proj_data["title"] == "Projet à restaurer §18.7"
        assert restored_proj_data["status"] == "Pret_pour_edition"

        # B. Les répliques restaurées sont intégrales et en ordre
        resp_r_after = client.get(
            f"/api/v1/projects/{project.id}/replicas", headers=headers
        )
        assert resp_r_after.status_code == 200
        restored_replicas = resp_r_after.json()
        assert len(restored_replicas) == 4
        assert (
            "Réplique #1 avant sinistre" in restored_replicas[0]["text"]
        )

        # C. Test d'écriture / édition interactive sur le système restauré -> 200 OK
        resp_edit = client.patch(
            f"/api/v1/replicas/{first_replica_id}",
            json={
                "text": "Texte édité et validé APRÈS restauration PRA/PCA §18.7",
                "version": 1,
            },
            headers=headers,
        )
        assert resp_edit.status_code == 200, (
            f"L'édition sur une réplique restaurée doit fonctionner : {resp_edit.text}"
        )
        assert (
            resp_edit.json()["replica"]["text"]
            == "Texte édité et validé APRÈS restauration PRA/PCA §18.7"
        )

        # D. Test de création d'un export sur le projet restauré -> 202 Accepted
        resp_exp = client.post(
            f"/api/v1/projects/{project.id}/exports",
            json={"format": "pdf"},
            headers=headers,
        )
        assert (
            resp_exp.status_code == 202
        ), "Le système restauré doit être pleinement opérationnel en génération d'export"

    finally:
        cleanup_pra_test_data(test_backup_dir, test_remote_media_dir)
        db.close()
