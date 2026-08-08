"""
Test d'intégration pour la détection et classification des zones de silence Silero-VAD (§8.2.4)
et leur persistance en SilenceEvent (§9.2).
Condition d'achèvement :
- test sur un extrait audio de test vérifiant la classification correcte d'au moins un exemple de chaque type de silence :
  1. respiration audible (pic d'énergie hautes fréquences avant reprise)
  2. pause syntaxique > 300ms
  3. hésitation < 200ms
  4. coupe technique (silence total 0 RMS)
"""

import os
import uuid
import pytest
from pathlib import Path
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
    SilenceEvent,
    AuditLog,
    SecurityAlert,
    set_allow_audit_log_purge,
)
from app.ai.silero_vad import SileroVADSilenceDetector
from app.services.silence_service import SilenceService

client = TestClient(app)


def get_db_session() -> Session:
    return SessionLocal()


def cleanup_silence_test_data():
    db = get_db_session()
    try:
        set_allow_audit_log_purge(True)
        try:
            db.query(AuditLog).filter(
                AuditLog.user_email == "silence_admin@studio.com"
            ).delete(synchronize_session=False)
            db.query(SecurityAlert).filter(
                SecurityAlert.user_email == "silence_admin@studio.com"
            ).delete(synchronize_session=False)
        finally:
            set_allow_audit_log_purge(False)

        studio = (
            db.query(Studio)
            .filter(Studio.name == "Studio Silence §8.2.4")
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
                    db.query(SilenceEvent).filter(
                        SilenceEvent.media_id == m.id
                    ).delete(synchronize_session=False)
                    db.query(MediaAsset).filter(
                        MediaAsset.id == m.id
                    ).delete(synchronize_session=False)
                db.query(Project).filter(Project.id == p.id).delete(
                    synchronize_session=False
                )
            user = (
                db.query(User)
                .filter(User.email == "silence_admin@studio.com")
                .first()
            )
            if user:
                from app.models import StudioMembership

                db.query(StudioMembership).filter(
                    StudioMembership.user_id == user.id
                ).delete(synchronize_session=False)
                db.delete(user)
            db.delete(studio)

        db.commit()
    finally:
        db.close()


def test_silero_vad_silence_classification_on_test_audio_and_persistence():
    """
    CONDITION D'ACHÈVEMENT :
    Test sur un extrait audio de test vérifiant la classification correcte
    d'au moins un exemple de chaque type de silence (§8.2.4, §9.2).
    """
    cleanup_silence_test_data()
    test_audio_path = "/tmp/test_silences_8_2_4.wav"

    try:
        # ------------------------------------------------------------------
        # 1. GÉNÉRATION DE L'EXTRAIT AUDIO DE TEST ET VÉRIFICATION VAD (§8.2.4)
        # ------------------------------------------------------------------
        # Générer le WAV synthétique contenant les 4 types de silence
        gen_path = SileroVADSilenceDetector.create_synthetic_test_audio(
            test_audio_path
        )
        assert os.path.exists(
            gen_path
        ), "Le fichier audio de test doit être généré"
        assert os.path.getsize(gen_path) > 1000

        detector = SileroVADSilenceDetector(speech_threshold=0.15)
        events = detector.detect_and_classify(gen_path)

        assert (
            len(events) == 4
        ), f"Exactement 4 zones de silence attendues, trouvé {len(events)}"

        # Extraire tous les event_type détectés
        types_found = {e["event_type"] for e in events}
        print(f"\n[VAD §8.2.4] Types de silences classifiés : {types_found}")

        # VÉRIFICATION DE LA CONDITION D'ACHÈVEMENT :
        # Au moins un exemple de chaque type de silence doit être correctement classifié
        assert (
            "coupe_technique" in types_found
        ), "Au moins une 'coupe technique' (silence total 0 RMS) doit être détectée"
        assert (
            "hesitation" in types_found
        ), "Au moins une 'hésitation' (< 200 ms) doit être détectée"
        assert (
            "pause_syntaxique" in types_found
        ), "Au moins une 'pause syntaxique' (> 300 ms) doit être détectée"
        assert (
            "respiration_audible" in types_found
        ), "Au moins une 'respiration audible' (hautes fréq/breath noise) doit être détectée"

        # Vérification détaillée des attributs acoustiques de chaque classification
        ev_coupe = next(e for e in events if e["event_type"] == "coupe_technique")
        assert (
            ev_coupe["details"]["rms"] == 0.0
        ), "Une coupe technique doit présenter une énergie RMS nulle"

        ev_hesit = next(e for e in events if e["event_type"] == "hesitation")
        assert (
            ev_hesit["duration_ms"] < 200
        ), f"Une hésitation doit durer < 200 ms ({ev_hesit['duration_ms']} ms)"

        ev_pause = next(
            e for e in events if e["event_type"] == "pause_syntaxique"
        )
        assert (
            ev_pause["duration_ms"] > 300
        ), f"Une pause syntaxique doit durer > 300 ms ({ev_pause['duration_ms']} ms)"

        ev_resp = next(
            e for e in events if e["event_type"] == "respiration_audible"
        )
        assert (
            ev_resp["details"]["zcr"] > 0.20
        ), f"Une respiration audible doit présenter une haute fréquence (ZCR={ev_resp['details']['zcr']})"

        # ------------------------------------------------------------------
        # 2. PERSISTANCE EN BASE DANS SilenceEvent (§9.2) & APIS REST
        # ------------------------------------------------------------------
        db = get_db_session()
        try:
            studio = Studio(
                id=uuid.uuid4(), name="Studio Silence §8.2.4", plan="pro"
            )
            project = Project(
                id=uuid.uuid4(),
                studio_id=studio.id,
                title="Projet Silences",
                source_lang="fr",
                target_lang="fr",
                status="Pret_pour_edition",
            )
            media = MediaAsset(
                id=uuid.uuid4(),
                project_id=project.id,
                storage_path=test_audio_path,
                status="confirmed",
            )
            db.add_all([studio, project, media])
            db.commit()
            db.refresh(media)

            user = User(
                id=uuid.uuid4(),
                email="silence_admin@studio.com",
                hashed_password=hash_password("SilenceSafe_Admin_99!@#"),
                role="owner",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

            from app.models import StudioMembership

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

            # A. Appel de l'endpoint de détection et persistance API
            resp_detect = client.post(
                f"/api/v1/media/{media.id}/silences/detect",
                headers=headers,
            )
            assert resp_detect.status_code == 201
            detect_data = resp_detect.json()
            assert len(detect_data) == 4
            api_types = {item["event_type"] for item in detect_data}
            assert api_types == {
                "coupe_technique",
                "hesitation",
                "pause_syntaxique",
                "respiration_audible",
            }

            # B. Vérification directe en base que les entités SilenceEvent (§9.2) sont créées
            db_events = (
                db.query(SilenceEvent)
                .filter(SilenceEvent.media_id == media.id)
                .order_by(SilenceEvent.start_ms)
                .all()
            )
            assert len(db_events) == 4
            assert db_events[0].event_type == "coupe_technique"
            assert db_events[0].duration_ms == 400
            assert db_events[1].event_type == "hesitation"
            assert db_events[2].event_type == "pause_syntaxique"
            assert db_events[3].event_type == "respiration_audible"

            # C. Vérification de l'endpoint de consultation GET /api/v1/media/{id}/silences
            resp_get = client.get(
                f"/api/v1/media/{media.id}/silences",
                headers=headers,
            )
            assert resp_get.status_code == 200
            assert len(resp_get.json()) == 4

        finally:
            db.close()

    finally:
        cleanup_silence_test_data()
        if os.path.exists(test_audio_path):
            try:
                os.remove(test_audio_path)
            except Exception:
                pass
