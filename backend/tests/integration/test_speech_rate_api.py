"""
Test d'intégration pour l'API REST de calcul et surveillance du débit d'élocution (§12.3)
et la remonte automatique d'alerte lors de l'édition d'une réplique.
"""

import uuid
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
    set_allow_audit_log_purge,
)

client = TestClient(app)


def get_db_session() -> Session:
    return SessionLocal()


def cleanup_speech_rate_data():
    db = get_db_session()
    try:
        set_allow_audit_log_purge(True)
        try:
            studio = (
                db.query(Studio)
                .filter(Studio.name == "Studio Speech Rate §12.3")
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
                    .filter(User.email == "adaptateur_sr@studio.com")
                    .first()
                )
                if user:
                    from app.models import StudioMembership

                    db.query(StudioMembership).filter(
                        StudioMembership.user_id == user.id
                    ).delete(synchronize_session=False)
                    db.delete(user)
                db.delete(studio)
        finally:
            set_allow_audit_log_purge(False)
        db.commit()
    finally:
        db.close()


def test_speech_rate_api_and_replica_patch_alert_trigger():
    cleanup_speech_rate_data()
    db = get_db_session()
    try:
        # 1. Vérifier l'endpoint de consultation des seuils configurés par langue (§12.3)
        resp_thresh = client.get("/api/v1/speech-rate/thresholds")
        assert resp_thresh.status_code == 200
        t_data = resp_thresh.json()
        assert "fr" in t_data["thresholds_by_language"]
        assert t_data["thresholds_by_language"]["fr"]["min_rate"] == 5.0
        assert t_data["thresholds_by_language"]["fr"]["max_rate"] == 7.0

        # 2. Vérifier l'endpoint d'évaluation REST POST /api/v1/speech-rate/evaluate
        resp_eval = client.post(
            "/api/v1/speech-rate/evaluate",
            json={
                "text": "Bonjour à tous les comédiens du studio Rythmo",  # 13 syllabes
                "duration_ms": 1200,  # 1.2 s -> 10.83 syll/s > 7.0
                "language": "fr",
            },
        )
        assert resp_eval.status_code == 200
        eval_res = resp_eval.json()
        assert eval_res["syllable_count"] == 13
        assert eval_res["is_alert"] is True
        assert eval_res["alert_type"] == "too_fast"

        # 3. Vérifier le déclenchement de l'alerte de débit lors du PATCH d'une réplique
        studio = Studio(
            id=uuid.uuid4(), name="Studio Speech Rate §12.3", plan="pro"
        )
        project = Project(
            id=uuid.uuid4(),
            studio_id=studio.id,
            title="Projet Débit",
            source_lang="fr",
            target_lang="fr",
            status="Pret_pour_edition",
        )
        media = MediaAsset(
            id=uuid.uuid4(),
            project_id=project.id,
            storage_path="speech_rate.mp4",
            status="confirmed",
        )
        db.add_all([studio, project, media])
        db.commit()
        db.refresh(media)

        replica = Replica(
            id=uuid.uuid4(),
            media_id=media.id,
            start_ms=0,
            end_ms=2000,
            text="Texte de départ court",
            order_index=0,
            version=1,
            confidence_score=0.92,
        )
        db.add(replica)
        db.commit()
        db.refresh(replica)

        user = User(
            id=uuid.uuid4(),
            email="adaptateur_sr@studio.com",
            hashed_password=hash_password("SpeechSafe_Admin_99!@#"),
            role="adaptateur",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        from app.models import StudioMembership

        db.add(
            StudioMembership(
                studio_id=studio.id, user_id=user.id, role="adaptateur"
            )
        )
        db.commit()

        token = create_access_token(
            {
                "sub": str(user.id),
                "email": user.email,
                "role": "adaptateur",
            }
        )
        headers = {"Authorization": f"Bearer {token}"}

        # L'adaptateur modifie la réplique en saisissant une très longue phrase sur une durée courte (1.0 s)
        fast_text = "Cette très longue phrase compte beaucoup trop de syllabes à prononcer en une seule seconde"
        resp_patch = client.patch(
            f"/api/v1/replicas/{replica.id}",
            json={
                "text": fast_text,
                "start_ms": 0,
                "end_ms": 1000,
                "version": 1,
            },
            headers=headers,
        )
        assert resp_patch.status_code == 200
        patch_res = resp_patch.json()
        rep_data = patch_res["replica"]

        assert rep_data["syllable_count"] > 15
        assert rep_data["speech_rate"] > 7.0
        assert rep_data["speech_rate_alert"] is not None
        assert rep_data["speech_rate_alert"]["is_alert"] is True
        assert rep_data["speech_rate_alert"]["alert_type"] == "too_fast"
        assert (
            "trop élevé"
            in rep_data["speech_rate_alert"]["alert_message"].lower()
        )

    finally:
        cleanup_speech_rate_data()
        db.close()
