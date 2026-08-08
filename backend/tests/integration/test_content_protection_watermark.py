import uuid
from datetime import datetime, timedelta, timezone
import pytest
from pypdf import PdfReader
import io
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from app.core.auth_handler import create_access_token
from app.models import Studio, Project, MediaAsset, Replica, User, Export

client = TestClient(app)


def get_db_session() -> Session:
    return SessionLocal()


def cleanup_test_data():
    db = get_db_session()
    try:
        db.query(Export).filter(
            Export.created_by.in_(
                ["guest_user@studio.com", "internal_user@studio.com"]
            )
        ).delete(synchronize_session=False)
        db.query(User).filter(
            User.email.in_(
                ["guest_user@studio.com", "internal_user@studio.com"]
            )
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_content_protection_watermark_and_security_toggles():
    cleanup_test_data()
    db = get_db_session()
    try:
        # 1. Setup Studio et Projet de test
        studio = Studio(
            id=uuid.uuid4(), name="Studio Protection Test", plan="pro"
        )
        db.add(studio)
        db.commit()
        db.refresh(studio)

        project = Project(
            id=uuid.uuid4(),
            studio_id=studio.id,
            title="Watermark Protection Project",
            source_lang="fr",
            target_lang="fr",
            status="draft",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        media = MediaAsset(
            id=uuid.uuid4(),
            project_id=project.id,
            storage_path="protection_test.mp4",
            status="confirmed",
        )
        db.add(media)
        db.commit()

        replica = Replica(
            id=uuid.uuid4(),
            media_id=media.id,
            start_ms=0,
            end_ms=2500,
            text="Réplique pour test filigrane dynamique.",
            order_index=0,
            confidence_score=0.95,
        )
        db.add(replica)
        db.commit()

        # 2. Création de deux utilisateurs : rôle à risque (Invité) et rôle interne (Adaptateur)
        guest_user = User(
            id=uuid.uuid4(),
            email="guest_user@studio.com",
            hashed_password="hashed_pw_here",
            role="invité",
            is_active=True,
        )
        internal_user = User(
            id=uuid.uuid4(),
            email="internal_user@studio.com",
            hashed_password="hashed_pw_here",
            role="adaptateur",
            is_active=True,
        )
        db.add_all([guest_user, internal_user])
        db.commit()
        db.refresh(guest_user)
        db.refresh(internal_user)

        guest_token = create_access_token(
            {"sub": str(guest_user.id), "email": guest_user.email, "role": "invité"}
        )
        internal_token = create_access_token(
            {
                "sub": str(internal_user.id),
                "email": internal_user.email,
                "role": "adaptateur",
            }
        )

        headers_guest = {"Authorization": f"Bearer {guest_token}"}
        headers_internal = {"Authorization": f"Bearer {internal_token}"}

        # ------------------------------------------------------------------
        # CONDITION D'ACHÈVEMENT :
        # Test vérifiant la présence du watermark sur un export généré
        # par un utilisateur au rôle Invité, absent pour un rôle interne
        # ------------------------------------------------------------------

        # A. Export généré par un utilisateur Invité -> Watermark DOIT être présent
        resp_export_guest = client.post(
            f"/api/v1/projects/{project.id}/exports",
            json={"format": "pdf"},
            headers=headers_guest,
        )
        assert resp_export_guest.status_code == 202
        export_guest_data = resp_export_guest.json()
        assert export_guest_data["is_watermarked"] is True
        assert export_guest_data["created_by"] == "guest_user@studio.com"
        assert export_guest_data["creator_role"] == "invité"
        export_id_guest = export_guest_data["id"]

        # Télécharger l'export PDF du guest et vérifier l'incrustation du watermark
        resp_dl_guest = client.get(
            f"/api/v1/exports/{export_id_guest}/download",
            headers=headers_guest,
        )
        assert resp_dl_guest.status_code == 200
        assert resp_dl_guest.headers["content-type"] == "application/pdf"

        pdf_guest = PdfReader(io.BytesIO(resp_dl_guest.content))
        text_guest = pdf_guest.pages[0].extract_text()
        assert (
            "WATERMARK" in text_guest or "FILIGRANE" in text_guest
        ), f"Watermark manquant pour un utilisateur Invité. Texte: {text_guest[:300]}"
        assert "guest_user@studio.com" in text_guest
        assert "invité" in text_guest.lower()

        # B. Export généré par un rôle interne (Adaptateur) -> Watermark DOIT être absent
        resp_export_internal = client.post(
            f"/api/v1/projects/{project.id}/exports",
            json={"format": "pdf"},
            headers=headers_internal,
        )
        assert resp_export_internal.status_code == 202
        export_int_data = resp_export_internal.json()
        assert export_int_data["is_watermarked"] is False
        assert export_int_data["created_by"] == "internal_user@studio.com"
        assert export_int_data["creator_role"] == "adaptateur"
        export_id_int = export_int_data["id"]

        # Télécharger l'export PDF interne et vérifier que le watermark est ABSENT
        resp_dl_int = client.get(
            f"/api/v1/exports/{export_id_int}/download",
            headers=headers_internal,
        )
        assert resp_dl_int.status_code == 200
        pdf_int = PdfReader(io.BytesIO(resp_dl_int.content))
        text_int = pdf_int.pages[0].extract_text()
        assert (
            "WATERMARK" not in text_int and "FILIGRANE CONFIDENTIEL" not in text_int
        ), "Watermark ne devrait pas être présent pour un rôle interne."

        # ------------------------------------------------------------------
        # VÉRIFICATION DU PARAMÉTRAGE (COCHAGE / DÉCOCHAGE DES CASES)
        # ------------------------------------------------------------------
        # Consultation des paramètres de sécurité du studio
        resp_sec = client.get(f"/api/v1/studios/{studio.id}/security")
        assert resp_sec.status_code == 200
        sec_data = resp_sec.json()
        assert sec_data["watermark_enabled"] is True
        assert sec_data["encryption_at_rest_enabled"] is True
        assert sec_data["encryption_in_transit_enabled"] is True
        assert sec_data["auto_purge_enabled"] is True
        assert sec_data["retention_days"] == 30

        # Décocher la case "watermark_enabled" pour le studio
        resp_patch_sec = client.patch(
            f"/api/v1/studios/{studio.id}/security",
            json={"watermark_enabled": False},
        )
        assert resp_patch_sec.status_code == 200
        assert resp_patch_sec.json()["watermark_enabled"] is False

        # Lorsqu'on décoche la case, même un Invité ne reçoit plus de watermark
        resp_export_guest_no_wm = client.post(
            f"/api/v1/projects/{project.id}/exports",
            json={"format": "pdf"},
            headers=headers_guest,
        )
        assert resp_export_guest_no_wm.status_code == 202
        assert resp_export_guest_no_wm.json()["is_watermarked"] is False

        # Recocher et tester les autres cases (chiffrement au repos, en transit, purge)
        resp_patch_all = client.patch(
            f"/api/v1/studios/{studio.id}/security",
            json={
                "watermark_enabled": True,
                "encryption_at_rest_enabled": True,
                "encryption_in_transit_enabled": True,
                "auto_purge_enabled": True,
                "retention_days": 15,
            },
        )
        assert resp_patch_all.status_code == 200
        assert resp_patch_all.json()["retention_days"] == 15

        # ------------------------------------------------------------------
        # CHIFFREMENT EN TRANSIT (TLS 1.3 OBLIGATOIRE, HSTS)
        # ------------------------------------------------------------------
        # Tous les flux HTTP reçoivent l'en-tête HSTS
        resp_hsts = client.get("/health")
        assert resp_hsts.status_code == 200
        assert (
            "max-age=31536000" in resp_hsts.headers["strict-transport-security"]
        )

        # Si un proxy envoie X-SSL-Protocol inférieur à TLSv1.3 (ex. TLSv1.2), refuser
        resp_old_tls = client.get(
            "/health", headers={"x-ssl-protocol": "TLSv1.2"}
        )
        assert resp_old_tls.status_code == 426
        assert "tls 1.3" in resp_old_tls.json()["detail"].lower()

        # TLS 1.3 explicite ou connexion directe -> autorisé
        resp_new_tls = client.get(
            "/health", headers={"x-ssl-protocol": "TLSv1.3"}
        )
        assert resp_new_tls.status_code == 200

        # ------------------------------------------------------------------
        # PURGE AUTOMATIQUE CONFIGURABLE DES EXPORTS APRÈS 30 JOURS (§15.4)
        # ------------------------------------------------------------------
        # Création d'un export expiré (simulé dans le passé)
        expired_export = Export(
            id=uuid.uuid4(),
            project_id=project.id,
            format="pdf",
            status="completed",
            created_by="guest_user@studio.com",
            creator_role="invité",
            is_watermarked=True,
            is_archived=False,
            expires_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        db.add(expired_export)
        db.commit()

        # L'export expiré est bien supprimé par la purge automatique
        resp_purge = client.post("/api/v1/exports/purge-expired")
        assert resp_purge.status_code == 200
        assert resp_purge.json()["purged_count"] >= 1
        assert (
            db.query(Export).filter(Export.id == expired_export.id).first()
            is None
        )

        # Création d'un export expiré mais ARCHIVÉ EXPLICITEMENT
        archived_export = Export(
            id=uuid.uuid4(),
            project_id=project.id,
            format="pdf",
            status="completed",
            created_by="internal_user@studio.com",
            creator_role="adaptateur",
            is_watermarked=False,
            is_archived=True,
            expires_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        db.add(archived_export)
        db.commit()

        # L'export archivé ne doit JAMAIS être purgé (sauf archivage explicite)
        resp_purge_2 = client.post("/api/v1/exports/purge-expired")
        assert resp_purge_2.status_code == 200
        assert (
            db.query(Export).filter(Export.id == archived_export.id).first()
            is not None
        )

        # Test de l'endpoint explicite d'archivage d'un export
        resp_archive = client.post(
            f"/api/v1/exports/{export_id_int}/archive",
            headers=headers_internal,
        )
        assert resp_archive.status_code == 200
        assert resp_archive.json()["is_archived"] is True

    finally:
        cleanup_test_data()
        db.close()
