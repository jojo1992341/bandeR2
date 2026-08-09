"""
Test d'intégration de la pipeline CD (§19.3) et du parcours critique e2e (§19.2).
Condition d'achèvement :
- un merge sur main déclenche un déploiement recette réussi (copie archive + install.ps1 -Update + NSSM)
- conservation de la version précédente pour rollback rapide
- packaging de l'artefact de livraison en .zip versionné
- la suite e2e passe intégralement sur cet environnement (import → pipeline → édition → export)
"""

import os
import shutil
import uuid
import zipfile
from pathlib import Path
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from tests.integration._infra import PIPELINE_SKIP_REASON, pipeline_infra_ready
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
    PipelineJob,
    set_allow_audit_log_purge,
)
from app.tasks.pipeline import (
    pipeline_extract_normalize,
    pipeline_transcribe_diarize,
    pipeline_generate_rythmo,
    notify_completion,
)

client = TestClient(app)


def get_db_session() -> Session:
    return SessionLocal()


def cleanup_cd_test_data(
    test_releases_dir: Path, test_recette_dir: Path
):
    db = get_db_session()
    try:
        set_allow_audit_log_purge(True)
        try:
            db.query(AuditLog).filter(
                AuditLog.user_email == "cd_recette@studio.com"
            ).delete(synchronize_session=False)
            db.query(SecurityAlert).filter(
                SecurityAlert.user_email == "cd_recette@studio.com"
            ).delete(synchronize_session=False)
        finally:
            set_allow_audit_log_purge(False)

        db.query(Export).filter(
            Export.created_by == "cd_recette@studio.com"
        ).delete(synchronize_session=False)

        studio = (
            db.query(Studio)
            .filter(Studio.name == "Recette CD Studio §19.3")
            .first()
        )
        if studio:
            projects = (
                db.query(Project)
                .filter(Project.studio_id == studio.id)
                .all()
            )
            for p in projects:
                db.query(PipelineJob).filter(
                    PipelineJob.project_id == p.id
                ).delete(synchronize_session=False)
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
                .filter(User.email == "cd_recette@studio.com")
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

    # Nettoyage des dossiers de livraison de test
    if test_releases_dir.exists():
        try:
            shutil.rmtree(test_releases_dir)
        except Exception:
            pass
    if test_recette_dir.exists():
        try:
            shutil.rmtree(test_recette_dir)
        except Exception:
            pass


def test_cd_pipeline_package_release_deploy_recette_and_rollback_ready():
    """
    CONDITION D'ACHÈVEMENT CD (§19.3) :
    1. Packaging de l'artefact de livraison en archive .zip versionnée
    2. Déploiement automatique en recette (copie archive + install.ps1 -Update + redémarrage NSSM)
    3. Conservation de la version précédente pour rollback rapide
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    test_releases_dir = repo_root / "deploy" / "test_releases"
    test_recette_dir = repo_root / "deploy" / "test_recette"
    cleanup_cd_test_data(test_releases_dir, test_recette_dir)

    try:
        import sys
        import importlib.util

        pkg_script = repo_root / "deploy" / "package_release.py"
        deploy_script = repo_root / "deploy" / "deploy_recette.py"
        assert pkg_script.exists(), "deploy/package_release.py est requis"
        assert deploy_script.exists(), "deploy/deploy_recette.py est requis"

        # Dynamically import scripts
        spec_pkg = importlib.util.spec_from_file_location(
            "package_release", str(pkg_script)
        )
        mod_pkg = importlib.util.module_from_spec(spec_pkg)
        spec_pkg.loader.exec_module(mod_pkg)

        spec_dep = importlib.util.spec_from_file_location(
            "deploy_recette", str(deploy_script)
        )
        mod_dep = importlib.util.module_from_spec(spec_dep)
        spec_dep.loader.exec_module(mod_dep)

        # A. PACKAGING DE L'ARTEFACT DE LIVRAISON EN ARCHIVE .ZIP VERSIONNÉE (§19.2 / §19.3)
        res_pkg1 = mod_pkg.package_delivery_artifact(
            version="2.0.0-rc1",
            output_dir=test_releases_dir,
            repo_root=repo_root,
        )
        assert res_pkg1["status"] == "success"
        archive_path1 = Path(res_pkg1["archive_path"])
        assert (
            archive_path1.exists()
        ), "L'archive .zip versionnée doit être créée"
        assert archive_path1.stat().st_size > 1000

        # Vérifier le contenu de l'archive (backend, config, scripts .ps1/.bat)
        with zipfile.ZipFile(archive_path1, "r") as zf:
            namelist = zf.namelist()
            assert any(
                "requirements.txt" in name for name in namelist
            ), "backend/requirements.txt doit être dans le .zip"
            assert any(
                "install.ps1" in name for name in namelist
            ), "install.ps1 doit être dans le .zip"
            assert any(
                "install-service.ps1" in name for name in namelist
            ), "install-service.ps1 doit être dans le .zip"

        # B. DÉPLOIEMENT AUTOMATIQUE EN RECETTE (§19.3)
        res_deploy1 = mod_dep.deploy_to_recette(
            archive_path=archive_path1,
            target_dir=test_recette_dir,
            releases_dir=test_releases_dir,
            repo_root=repo_root,
        )
        assert res_deploy1["status"] == "success"
        assert res_deploy1["environment"] == "recette"
        assert (
            "alembic upgrade head" in res_deploy1["migrations"]
        )
        assert res_deploy1["services_restarted"] is True

        # Vérifier sur disque la présence de l'application déployée dans l'environnement de recette
        assert (
            test_recette_dir / "backend" / "requirements.txt"
        ).exists()
        assert (test_recette_dir / "install.ps1").exists()

        # C. CONSERVATION DE LA VERSION PRÉCÉDENTE POUR ROLLBACK RAPIDE (§19.3)
        # Packaging d'une V2 (2.0.0-rc2) pour déclencher le second déploiement
        res_pkg2 = mod_pkg.package_delivery_artifact(
            version="2.0.0-rc2",
            output_dir=test_releases_dir,
            repo_root=repo_root,
        )
        assert res_pkg2["status"] == "success"
        archive_path2 = Path(res_pkg2["archive_path"])

        res_deploy2 = mod_dep.deploy_to_recette(
            archive_path=archive_path2,
            target_dir=test_recette_dir,
            releases_dir=test_releases_dir,
            repo_root=repo_root,
        )
        assert res_deploy2["status"] == "success"
        # La version précédente doit maintenant être disponible
        previous_path = test_releases_dir / "rythmoai-release-previous.zip"
        assert (
            previous_path.exists()
        ), "L'archive de la version précédente doit être conservée pour rollback rapide (§19.3)"

        # D. TEST DU ROLLBACK RAPIDE (§19.3)
        res_rollback = mod_dep.rollback_recette(
            target_dir=test_recette_dir,
            releases_dir=test_releases_dir,
        )
        assert res_rollback["status"] == "rolled_back"
        assert res_rollback["environment"] == "recette"

    finally:
        cleanup_cd_test_data(test_releases_dir, test_recette_dir)


@pytest.mark.skipif(not pipeline_infra_ready(), reason=PIPELINE_SKIP_REASON)
def test_e2e_critical_journey_import_pipeline_editing_export_on_recette():
    """
    CONDITION D'ACHÈVEMENT E2E (§19.2 / §19.3) :
    La suite e2e passe intégralement sur cet environnement de recette :
    Parcours critique complet : IMPORT → PIPELINE → ÉDITION → EXPORT
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    test_releases_dir = repo_root / "deploy" / "test_releases_e2e"
    test_recette_dir = repo_root / "deploy" / "test_recette_e2e"
    cleanup_cd_test_data(test_releases_dir, test_recette_dir)

    db = get_db_session()
    try:
        # 0. SETUP COMPTE & STUDIO EN RECETTE
        studio = Studio(
            id=uuid.uuid4(), name="Recette CD Studio §19.3", plan="pro"
        )
        db.add(studio)
        db.commit()
        db.refresh(studio)

        user = User(
            id=uuid.uuid4(),
            email="cd_recette@studio.com",
            hashed_password=hash_password("RecetteSafe_Admin_99!@#"),
            role="owner",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        db.add(
            StudioMembership(
                studio_id=studio.id, user_id=user.id, role="owner"
            )
        )
        db.commit()

        token = create_access_token(
            {"sub": str(user.id), "email": user.email, "role": "owner"}
        )
        headers = {"Authorization": f"Bearer {token}"}

        # ==================================================================
        # ÉTAPE 1 : IMPORT VIDÉO (§10.2 / §19.2)
        # ==================================================================
        resp_proj = client.post(
            "/api/v1/projects",
            json={
                "title": "Vidéo Recette E2E §19.2",
                "studio_id": str(studio.id),
                "source_lang": "fr",
                "target_lang": "fr",
            },
            headers=headers,
        )
        assert resp_proj.status_code == 201
        project_id = resp_proj.json()["id"]

        # Générer l'URL d'upload S3/MinIO
        resp_url = client.post(
            f"/projects/{project_id}/media/upload-url",
            json={
                "filename": "20min_e2e_recette.mp4",
                "content_type": "video/mp4",
            },
            headers=headers,
        )
        assert resp_url.status_code == 201
        upload_data = resp_url.json()
        media_id = upload_data["media_id"]

        # Upload de la vidéo sur le stockage S3 avant confirmation
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url="http://localhost:9000",
            aws_access_key_id="minioadmin",
            aws_secret_access_key="minioadmin",
        )
        try:
            s3.create_bucket(Bucket="rythmoai-media")
        except Exception:
            pass

        tmp_valid = "/tmp/test_valid.mp4"
        os.system(
            f"ffmpeg -f lavfi -i testsrc=duration=1:size=320x240:rate=1 -pix_fmt yuv420p {tmp_valid} -y 2>/dev/null"
        )
        s3.upload_file(tmp_valid, "rythmoai-media", upload_data["key"])

        # Confirmer le média post-upload
        resp_conf = client.post(
            f"/api/v1/media/{media_id}/confirm",
            json={"key": upload_data["key"]},
            headers=headers,
        )
        assert resp_conf.status_code == 200
        assert resp_conf.json()["status"] == "confirmed"

        # ==================================================================
        # ÉTAPE 2 : PIPELINE IA BOUT-EN-BOUT (§19.2)
        # ==================================================================
        # Exécution en séquence de la chaîne d'extraction, transcription, diarisation et bande rythmo
        video_path = "/tmp/test_video_piste.mp4"
        if not os.path.exists(video_path):
            import subprocess

            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=duration=2:size=320x240:rate=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=1000:duration=2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-shortest",
                    video_path,
                ],
                capture_output=True,
                timeout=30,
            )

        res1 = pipeline_extract_normalize.run(
            media_path=video_path, media_id=str(media_id)
        )
        assert res1 is not None and "extracted_tracks" in res1
        res2 = pipeline_transcribe_diarize.run(pipeline_result=res1)
        assert res2 is not None and "transcription" in res2
        res3 = pipeline_generate_rythmo.run(pipeline_result={**res1, **res2})
        assert res3 is not None

        # Renseigner un job complété et vérifier la notification
        res4 = notify_completion.run(
            pipeline_result={
                **res1,
                **res2,
                **res3,
                "project_id": str(project_id),
            }
        )
        assert res4.get("status") == "completed"

        # Générer la bande rythmo (création des répliques à partir des segments transcrits)
        resp_gen = client.post(
            f"/api/v1/projects/{project_id}/rythmo/generate",
            json={"media_id": str(media_id)},
            headers=headers,
        )
        assert resp_gen.status_code == 200

        # ==================================================================
        # ÉTAPE 3 : ÉDITION DE LA BANDE RYTHMO (§19.2)
        # ==================================================================
        # Vérifier que les répliques sont générées par la pipeline
        resp_replicas = client.get(
            f"/api/v1/projects/{project_id}/replicas", headers=headers
        )
        assert resp_replicas.status_code == 200
        replicas = resp_replicas.json()
        assert len(replicas) >= 1

        first_rep = replicas[0]
        rep_id = first_rep["id"]

        # Modifier le texte, timing et codes typographiques (§2.4, §9.4)
        resp_patch = client.patch(
            f"/api/v1/replicas/{rep_id}",
            json={
                "text": "Réplique parfaitement adaptée et calligraphiée en recette §19.2",
                "start_ms": 100,
                "end_ms": 1800,
                "typo_codes": {"crochets": True, "italique": True},
                "version": first_rep["version"] or 1,
            },
            headers=headers,
        )
        assert resp_patch.status_code == 200
        patch_data = resp_patch.json()
        assert patch_data["status"] == "updated"
        assert patch_data["is_manually_edited"] is True
        assert patch_data["typo_codes"]["crochets"] is True
        assert (
            patch_data["replica"]["text"]
            == "Réplique parfaitement adaptée et calligraphiée en recette §19.2"
        )

        # ==================================================================
        # ÉTAPE 4 : EXPORT DES LIVRABLES (PDF, SRT, VTT) (§19.2)
        # ==================================================================
        # 1. Export PDF calligraphié
        resp_pdf = client.post(
            f"/api/v1/projects/{project_id}/exports",
            json={"format": "pdf"},
            headers=headers,
        )
        assert resp_pdf.status_code == 202
        pdf_export = resp_pdf.json()
        assert pdf_export["status"] == "completed"
        pdf_id = pdf_export["id"]

        # Télécharger le PDF d'export
        resp_dl_pdf = client.get(
            f"/api/v1/exports/{pdf_id}/download", headers=headers
        )
        assert resp_dl_pdf.status_code == 200
        assert resp_dl_pdf.headers["content-type"] == "application/pdf"
        assert len(resp_dl_pdf.content) > 500

        # 2. Export SRT sous-titrage
        resp_srt = client.post(
            f"/api/v1/projects/{project_id}/exports",
            json={"format": "srt"},
            headers=headers,
        )
        assert resp_srt.status_code == 202
        srt_export = resp_srt.json()
        srt_id = srt_export["id"]
        resp_dl_srt = client.get(
            f"/api/v1/exports/{srt_id}/download", headers=headers
        )
        assert resp_dl_srt.status_code == 200
        assert "-->" in resp_dl_srt.text

        # 3. Export VTT
        resp_vtt = client.post(
            f"/api/v1/projects/{project_id}/exports",
            json={"format": "vtt"},
            headers=headers,
        )
        assert resp_vtt.status_code == 202
        vtt_id = resp_vtt.json()["id"]
        resp_dl_vtt = client.get(
            f"/api/v1/exports/{vtt_id}/download", headers=headers
        )
        assert resp_dl_vtt.status_code == 200
        assert "WEBVTT" in resp_dl_vtt.text

    finally:
        cleanup_cd_test_data(test_releases_dir, test_recette_dir)
        db.close()
