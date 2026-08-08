import uuid
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal
from app.models import Studio, Project, Speaker, Word, MediaAsset
from app.core.password import hash_password

def test_speaker_merge_reduces_count():
    db = SessionLocal()
    try:
        studio = Studio(id=uuid.uuid4(), name="Speaker Studio", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        proj = Project(id=uuid.uuid4(), studio_id=studio.id, title="S", source_lang="fr", target_lang="fr", status="draft")
        db.add(proj); db.commit(); db.refresh(proj)
        ma = MediaAsset(id=uuid.uuid4(), project_id=proj.id, storage_path="s.mp3", status="confirmed")
        db.add(ma); db.commit(); db.refresh(ma)
        spk_a = Speaker(id=uuid.uuid4(), project_id=proj.id, label="Alice", color="#e11d48")
        spk_b = Speaker(id=uuid.uuid4(), project_id=proj.id, label="Bob", color="#3b82f6")
        db.add_all([spk_a, spk_b]); db.commit(); db.refresh(spk_a); db.refresh(spk_b)
        # Mots liés
        db.add_all([
            Word(id=uuid.uuid4(), segment_id=ma.id, text="hello", speaker_id=spk_a.id, language="fr", confidence_score=0.92),
            Word(id=uuid.uuid4(), segment_id=ma.id, text="world", speaker_id=spk_b.id, language="fr", confidence_score=0.88),
        ])
        db.commit()
        # Avant fusion
        count_before = db.query(Speaker).filter(Speaker.project_id == proj.id).count()
        assert count_before == 2
        # Simuler fusion via endpoint (ici direct DB pour test rapide)
        for w in db.query(Word).filter(Word.speaker_id == spk_a.id).all():
            w.speaker_id = spk_b.id
        db.delete(spk_a)
        db.commit()
        count_after = db.query(Speaker).filter(Speaker.project_id == proj.id).count()
        assert count_after == 1, f"Fusion doit réduire à 1 locuteur, trouvé {count_after}"
        # Nettoyage
        db.query(Word).filter(Word.segment_id == ma.id).delete(synchronize_session=False)
        db.query(MediaAsset).filter(MediaAsset.id == ma.id).delete(synchronize_session=False)
        db.query(Project).filter(Project.id == proj.id).delete(synchronize_session=False)
        db.query(Speaker).filter(Speaker.id == spk_b.id).delete(synchronize_session=False)
        db.query(Studio).filter(Studio.id == studio.id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
