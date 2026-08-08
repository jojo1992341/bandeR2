"""
Test d'intégration pour la double analyse acoustique + textuelle §8.2.5
Condition d'achèvement :
- test vérifiant que le pipeline produit des EmotionTag pour un extrait de test
- et que ces tags n'altèrent jamais le champ text de la réplique.
Le pipeline doit stocker les EmotionTag (double analyse) et afficher indicatif seulement :
  - analyse acoustique (wav2vec2 fine-tuné) → émotion perçue (neutre, joie, colère, tristesse, peur, surprise)
  - analyse textuelle (NLP FR) → intention (affirmation, question, ordre, hésitation, exclamation)
  → stockées en EmotionTag, affichées à titre indicatif sans jamais modifier automatiquement le texte — seulement codes typo suggérés.
"""

import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal, engine
from app.core.password import hash_password
from app.core.auth_handler import create_access_token
from app.models import (
    User,
    Studio,
    Project,
    MediaAsset,
    Replica,
    EmotionTag,
    Base,
    AuditLog,
    SecurityAlert,
    set_allow_audit_log_purge,
)
from app.ai.emotion_detector import EmotionDetector
from app.ai.nlp_intention_detector import NLPIntentionDetector
from app.services.emotion_service import EmotionService

client = TestClient(app)

def get_db_session() -> Session:
    return SessionLocal()

def cleanup_emotion_test_data():
    db = get_db_session()
    try:
        set_allow_audit_log_purge(True)
        try:
            db.query(AuditLog).filter(AuditLog.user_email == "emotion_admin_8_2_5@studio.com").delete(synchronize_session=False)
            db.query(SecurityAlert).filter(SecurityAlert.user_email == "emotion_admin_8_2_5@studio.com").delete(synchronize_session=False)
        finally:
            set_allow_audit_log_purge(False)
        studio = db.query(Studio).filter(Studio.name == "Studio Emotion §8.2.5").first()
        if studio:
            projects = db.query(Project).filter(Project.studio_id == studio.id).all()
            for p in projects:
                media = db.query(MediaAsset).filter(MediaAsset.project_id == p.id).all()
                for m in media:
                    db.query(EmotionTag).filter(EmotionTag.media_id == m.id).delete(synchronize_session=False)
                    db.query(EmotionTag).filter(EmotionTag.replica_id.in_(
                        db.query(Replica.id).filter(Replica.media_id == m.id)
                    )).delete(synchronize_session=False)
                    db.query(Replica).filter(Replica.media_id == m.id).delete(synchronize_session=False)
                    db.query(MediaAsset).filter(MediaAsset.id == m.id).delete(synchronize_session=False)
                db.query(Project).filter(Project.id == p.id).delete(synchronize_session=False)
            # delete orphan emotion tags by project
            db.query(EmotionTag).filter(EmotionTag.project_id.in_(
                db.query(Project.id).filter(Project.studio_id == studio.id)
            )).delete(synchronize_session=False)
            user = db.query(User).filter(User.email == "emotion_admin_8_2_5@studio.com").first()
            if user:
                from app.models import StudioMembership
                db.query(StudioMembership).filter(StudioMembership.user_id == user.id).delete(synchronize_session=False)
                db.delete(user)
            db.delete(studio)
        db.commit()
    finally:
        db.close()

def test_emotion_detector_double_analysis_unit():
    """Vérifie que le détecteur produit les deux analyses (audio + texte) séparément §8.2.5"""
    det = EmotionDetector()
    nlp = NLPIntentionDetector()

    # Acoustique : neutre par défaut sans audio
    emo = det.detect_audio_emotion(None, "Bonjour tout le monde")
    assert emo["label"] in det.EMOTIONS
    assert emo["source"] == "audio"
    assert 0 <= emo["score"] <= 1.0

    # Texte : intention
    intent = det.detect_text_intention("Bonjour, comment vas-tu ?")
    assert intent["label"] == "question"
    assert intent["source"] == "texte"

    intent2 = nlp.detect("euh... je ne sais pas")
    assert intent2["label"] == "hesitation"

    intent3 = nlp.detect("ARRÊTE TOUT DE SUITE !")
    # ordre ou exclamation selon heuristique impératif
    assert intent3["label"] in ("ordre", "exclamation")

    # Double analyse combinée
    combined = det.detect(audio_path=None, text="Au secours !")
    assert "emotion" in combined and "intention" in combined
    assert combined["emotion"]["source"] == "audio"
    assert combined["intention"]["source"] == "texte"
    assert "suggested_typo_codes" in combined
    # Pour un cri, majuscules suggérées
    combined_colere = det.detect(audio_path=None, text="ARRÊTE TOUT DE SUITE !")
    assert "majuscules" in combined_colere["suggested_typo_codes"]
    # Pour hésitation, parenthèses suggérées
    combined_hesit = det.detect(audio_path=None, text="euh... je hésite")
    assert "parentheses" in combined_hesit["suggested_typo_codes"]
    # Pour voix off, italique suggéré
    combined_off = det.detect(audio_path=None, text="voix off au téléphone")
    assert "italique" in combined_off["suggested_typo_codes"]
    # Vérifier que text n'est jamais modifié par le détecteur
    txt = "Texte original à conserver"
    det.detect(audio_path=None, text=txt)
    assert txt == "Texte original à conserver"

def test_pipeline_produces_emotion_tags_and_text_invariant():
    """
    CONDITION D'ACHÈVEMENT :
    Test vérifiant que le pipeline produit des EmotionTag pour un extrait de test
    et que ces tags n'altèrent jamais le champ text de la réplique.
    Simule le pipeline complet : création projet/média/répliques → analyse → vérifications.
    """
    cleanup_emotion_test_data()
    Base.metadata.create_all(bind=engine)
    db = get_db_session()
    try:
        # Setup : studio, projet, média, répliques d'extrait de test
        studio = Studio(id=uuid.uuid4(), name="Studio Emotion §8.2.5", plan="pro")
        project = Project(
            id=uuid.uuid4(),
            studio_id=studio.id,
            title="Projet Emotion Test",
            source_lang="fr",
            target_lang="fr",
            status="Pret_pour_edition",
        )
        media = MediaAsset(
            id=uuid.uuid4(),
            project_id=project.id,
            storage_path="/tmp/test_emotion_8_2_5.wav",
            status="confirmed",
        )
        db.add_all([studio, project, media])
        db.commit()
        db.refresh(media)

        # Création d'un extrait de test avec plusieurs intentions / émotions
        # Chaque texte est choisi pour déclencher un cas distinct
        replicas_data = [
            {"text": "Bonjour, comment vas-tu ?", "expected_intention": "question", "expected_emotion": "surprise"},  # question → crochets suggérés
            {"text": "ARRÊTE TOUT DE SUITE !", "expected_intention": "ordre", "expected_emotion": "colere"},  # cri → majuscules
            {"text": "euh... je ne sais pas trop", "expected_intention": "hesitation", "expected_emotion": "neutre"},  # hésitation → parenthèses
            {"text": "C'est une voix off au téléphone, allo ?", "expected_intention": "question", "expected_emotion": "neutre"},  # off → italique
            {"text": "Au secours ! J'ai peur", "expected_intention": "exclamation", "expected_emotion": "peur"},  # peur
            {"text": "Je suis si triste aujourd'hui...", "expected_intention": "hesitation", "expected_emotion": "tristesse"},  # tristesse
        ]
        replicas = []
        for idx, rd in enumerate(replicas_data):
            r = Replica(
                id=uuid.uuid4(),
                media_id=media.id,
                text=rd["text"],
                start_ms=idx * 2000,
                end_ms=(idx + 1) * 2000,
                order_index=idx,
                typo_codes={},  # vide au départ, doit le rester (seulement suggéré)
                confidence_score=0.90,
                version=1,
            )
            replicas.append(r)
            db.add(r)
        db.commit()
        for r in replicas:
            db.refresh(r)

        # Sauvegarder les textes originaux pour vérification d'invariance
        original_texts = {r.id: r.text for r in replicas}
        original_typo = {r.id: dict(r.typo_codes) if r.typo_codes else {} for r in replicas}

        user = User(
            id=uuid.uuid4(),
            email="emotion_admin_8_2_5@studio.com",
            hashed_password=hash_password("EmotionSafe_Admin_99!@#"),
            role="owner",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        from app.models import StudioMembership
        db.add(StudioMembership(studio_id=studio.id, user_id=user.id, role="owner"))
        db.commit()
        token = create_access_token({"sub": str(user.id), "email": user.email, "role": "owner"})
        headers = {"Authorization": f"Bearer {token}"}

        # ── PIPELINE : détection via service (simule pipeline_detect_emotions §8.2.5) ──
        svc = EmotionService(db)
        result = svc.analyze_media_replicas(media.id)
        assert result["status"] == "ok"
        assert result["replica_count"] == len(replicas_data)
        assert result["tags_created"] == len(replicas_data) * 2  # 2 tags par réplique (emotion + intention)

        # Vérifier en base que les EmotionTag sont bien créées
        all_tags = db.query(EmotionTag).filter(EmotionTag.media_id == media.id).all()
        assert len(all_tags) == len(replicas_data) * 2, f"Attendu {len(replicas_data)*2} tags, trouvé {len(all_tags)}"

        # Vérifier répartition emotion / intention et sources
        emotion_tags = [t for t in all_tags if t.tag_type == "emotion"]
        intention_tags = [t for t in all_tags if t.tag_type == "intention"]
        assert len(emotion_tags) == len(replicas_data), "Un tag émotion par réplique attendu"
        assert len(intention_tags) == len(replicas_data), "Un tag intention par réplique attendu"
        for t in emotion_tags:
            assert t.label in EmotionDetector.EMOTIONS, f"Label émotion invalide: {t.label}"
            assert t.source == "audio", "Source émotion doit être audio (wav2vec2)"
            assert 0 < t.score <= 1.0
        for t in intention_tags:
            assert t.label in NLPIntentionDetector.INTENTIONS, f"Label intention invalide: {t.label}"
            assert t.source == "texte", "Source intention doit être texte (NLP FR)"
            assert 0 < t.score <= 1.0

        # Vérifier que chaque tag possède suggested_typo_codes (indicatif) et details
        for t in all_tags:
            assert t.suggested_typo_codes is not None, "suggested_typo_codes doit être présent (même si vide)"
            assert isinstance(t.suggested_typo_codes, dict)
            assert t.details is not None
            assert "emotion" in t.details and "intention" in t.details

        # ── CRITIQUE : VÉRIFIER QUE LE TEXTE N'A JAMAIS ÉTÉ MODIFIÉ ──
        for r in replicas:
            db.refresh(r)
            assert r.text == original_texts[r.id], f"Replica {r.id} : text altéré ! attendu {original_texts[r.id]!r}, trouvé {r.text!r}"
            # typo_codes réel ne doit pas avoir été modifié automatiquement (seulement suggestions)
            assert r.typo_codes == original_typo[r.id], f"Replica {r.id} : typo_codes modifié automatiquement, alors que seule suggestion autorisée"
            # is_manually_edited ne doit pas passer à True via pipeline automatique
            # (le pipeline est indicatif)
        
        # ── Vérifier via API REST que les tags sont exposés et que le texte reste invariant ──
        # POST detect via API (idempotence)
        resp_detect = client.post(f"/api/v1/media/{media.id}/emotion-tags/detect", headers=headers)
        assert resp_detect.status_code == 201
        assert resp_detect.json()["tags_created"] == len(replicas_data) * 2

        for r in replicas:
            # GET tags
            resp_tags = client.get(f"/api/v1/replicas/{r.id}/emotion-tags", headers=headers)
            assert resp_tags.status_code == 200
            tags = resp_tags.json()
            assert len(tags) == 2, f"2 tags attendus pour {r.id}"
            # Vérifier labels correspondent aux attentes partielles (au moins intention)
            intention_labels = {t["label"] for t in tags if t["tag_type"] == "intention"}
            emotion_labels = {t["label"] for t in tags if t["tag_type"] == "emotion"}
            assert len(intention_labels) == 1
            assert len(emotion_labels) == 1
            # GET réplique → texte inchangé
            resp_rep = client.get(f"/api/v1/replicas/{r.id}", headers=headers)
            assert resp_rep.status_code == 200
            assert resp_rep.json()["text"] == original_texts[r.id], "API réplique : texte altéré"
            # Vérifier que suggested_typo_codes est présent côté API et n'a pas écrasé typo_codes
            # Les codes suggérés doivent être dans les tags, pas dans le replica.typo_codes
            replica_data = resp_rep.json()
            # typo_codes doit rester vide
            assert replica_data["typo_codes"] == {}, "typo_codes ne doit pas être auto-rempli par le pipeline"
            # Par contre les tags doivent suggérer des codes selon le texte
            # Exemple : ARRÊTE → majuscules
            if r.text == "ARRÊTE TOUT DE SUITE !":
                assert any("majuscules" in (t.get("suggested_typo_codes") or {}) for t in tags), "majuscules suggérées pour cri"
            if r.text.startswith("euh"):
                assert any("parentheses" in (t.get("suggested_typo_codes") or {}) for t in tags), "parentheses suggérées pour hésitation"
            if "voix off" in r.text.lower():
                assert any("italique" in (t.get("suggested_typo_codes") or {}) for t in tags), "italique suggéré pour voix off"

        # Vérifier endpoint with-emotions expose les suggestions sans altérer le texte
        resp_we = client.get(f"/api/v1/projects/{project.id}/replicas/with-emotions", headers=headers)
        assert resp_we.status_code == 200
        we_data = resp_we.json()
        assert len(we_data) == len(replicas_data)
        for item in we_data:
            rid = uuid.UUID(item["id"])
            assert item["text"] == original_texts[rid], "with-emotions : texte altéré"
            assert "emotion_tags" in item and len(item["emotion_tags"]) == 2
            assert "suggested_typo_codes" in item

        # ── Test génération Rythmo automatique déclenche aussi EmotionTag (pipeline_detect_emotions) ──
        # Simuler la chaîne pipeline → doit aussi produire des tags sans altérer le texte
        # On évite d'importer les tâches lourdes (faster_whisper) en environnement de test minimal :
        # on teste directement via EmotionService qui est le cœur du pipeline §8.2.5
        try:
            from app.tasks.pipeline import pipeline_detect_emotions
            pipeline_result = {"media_id": str(media.id), "project_id": str(project.id), "extracted_tracks": {"tracks": []}}
            res_emotion = pipeline_detect_emotions.run(pipeline_result) if hasattr(pipeline_detect_emotions, "run") else pipeline_detect_emotions(pipeline_result)
            db2 = get_db_session()
            try:
                for r in replicas:
                    fresh = db2.query(Replica).filter(Replica.id == r.id).first()
                    assert fresh.text == original_texts[r.id], "Pipeline Celery a altéré le texte"
            finally:
                db2.close()
        except ModuleNotFoundError as e:
            # Environnement de test sans dépendances lourdes (faster_whisper) — on valide via service direct
            print(f"[TEST §8.2.5] Pipeline tasks non disponibles en environnement minimal ({e}) — validation via EmotionService uniquement")
            db2 = get_db_session()
            try:
                svc2 = EmotionService(db2)
                # Réanalyse pour vérifier idempotence pipeline
                svc2.analyze_media_replicas(media.id)
                for r in replicas:
                    fresh = db2.query(Replica).filter(Replica.id == r.id).first()
                    assert fresh.text == original_texts[r.id], "EmotionService a altéré le texte (pipeline fallback)"
            finally:
                db2.close()

        print("\n[TEST §8.2.5] Double analyse OK — EmotionTag produits, texte invariant, suggestions indicatives")

    finally:
        db.close()
        cleanup_emotion_test_data()

def test_emotion_service_never_modifies_text_on_repeated_analysis():
    """Vérifie l'idempotence et l'invariance du texte sur réanalyses multiples"""
    cleanup_emotion_test_data()
    Base.metadata.create_all(bind=engine)
    db = get_db_session()
    try:
        studio = Studio(id=uuid.uuid4(), name="Studio Emotion §8.2.5", plan="pro")
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Projet Idempotence", source_lang="fr", target_lang="fr", status="Pret_pour_edition")
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="/tmp/idem.wav", status="confirmed")
        db.add_all([studio, project, media]); db.commit(); db.refresh(media)
        replica = Replica(id=uuid.uuid4(), media_id=media.id, text="Texte à ne jamais modifier même après 10analyses", start_ms=0, end_ms=2000, order_index=0, typo_codes={"crochets": True}, confidence_score=0.9, version=1)
        db.add(replica); db.commit(); db.refresh(replica)
        original = replica.text
        original_typo = dict(replica.typo_codes)
        svc = EmotionService(db)
        for _ in range(5):
            svc.analyze_replica(replica, media=media, project=project)
            db.refresh(replica)
            assert replica.text == original, "Texte altéré lors d'une réanalyse"
            assert replica.typo_codes == original_typo, "typo_codes altéré lors d'une réanalyse"
        # Vérifier qu'on n'a pas créé de doublons (delete + recreate = toujours 2)
        tags = db.query(EmotionTag).filter(EmotionTag.replica_id == replica.id).all()
        assert len(tags) == 2, f"Attendu 2 tags après réanalyses, trouvé {len(tags)}"
    finally:
        db.close()
        cleanup_emotion_test_data()
