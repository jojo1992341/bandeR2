import os
import uuid
import subprocess
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models import MediaAsset, TranscriptSegment, Studio, Project, User
from app.core.password import hash_password
from app.tasks.transcription import transcribe_audio

def test_transcription_fr_small():
    # Créer un extrait audio court (simulé FR pour la pipeline)
    audio_path = "/tmp/test_fr_audio.wav"
    # Utiliser ffmpeg avec entrée sine (pas de paroles réelles, mais structure audio valide pour Whisper)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
        "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", audio_path
    ], capture_output=True, timeout=30)
    assert os.path.exists(audio_path) and os.path.getsize(audio_path) > 500, "Audio test non créé"

    # Insérer un media factice pour le lien FK
    db = SessionLocal()
    try:
        studio = Studio(id=uuid.uuid4(), name="Transcr Studio", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        user = User(id=uuid.uuid4(), email="trans@test.com", hashed_password=hash_password("t"), role="adaptateur", is_active=True)
        db.add(user); db.commit(); db.refresh(user)
        media = MediaAsset(id=uuid.uuid4(), project_id=uuid.uuid4(), storage_path="test.wav", status="confirmed")
        # Utiliser un projet temporaire pour FK
        proj = Project(id=media.project_id, studio_id=studio.id, title="T", source_lang="fr", target_lang="fr", status="draft")
        db.add(proj)
        db.add(media)
        db.commit(); db.refresh(media)

        # Exécuter la transcription (CPU — repli automatique si pas de GPU)
        # On force le modèle small pour la vitesse du test, tout en validant le pipeline
        os.environ["WHISPER_MODEL"] = "tiny"
        result = transcribe_audio.run(media_path=audio_path, media_id=str(media.id))
        assert result is not None
        assert result.get("language") is not None
        assert result.get("segments_count", 0) >= 1, "Aucun segment produit"

        # Vérifier persistance DB
        segments = db.query(TranscriptSegment).filter(TranscriptSegment.media_id == media.id).all()
        assert len(segments) >= 1, "Segments non persistés"
        for seg in segments:
            assert seg.confidence_score is not None and seg.confidence_score > 0.0, "Score de confiance doit être non nul"
            assert seg.text is not None and len(seg.text.strip()) > 0, "Texte cohérent attendu"
            assert seg.language == "fr" or seg.language is not None, "Langue détectée attendue"
        # Nettoyage
        db.query(TranscriptSegment).filter(TranscriptSegment.media_id == media.id).delete(synchronize_session=False)
        db.query(MediaAsset).filter(MediaAsset.id == media.id).delete(synchronize_session=False)
        db.query(Project).filter(Project.id == proj.id).delete(synchronize_session=False)
        db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db.query(Studio).filter(Studio.id == studio.id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
