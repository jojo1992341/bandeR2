from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.auth_handler import verify_token
from app.models import PipelineJob, Project, MediaAsset, Replica
from app.services.rythmo_engine import RythmoEngine
import uuid

router = APIRouter()

class RythmoGenerateIn(BaseModel):
    media_id: uuid.UUID

@router.post("/projects/{project_id}/rythmo/generate")
def generate_rythmo(project_id: uuid.UUID, data: RythmoGenerateIn, db: Session = Depends(get_db)):
    # Vérifier pipeline terminé (condition d'achèvement)
    job = db.query(PipelineJob).filter(PipelineJob.project_id == project_id).order_by(PipelineJob.updated_at.desc()).first()
    if not job or job.status != "Prêt pour édition" or job.progress_percent < 100:
        raise HTTPException(status_code=409, detail="Pipeline préalable non terminé — attendez la fin du traitement")
    media = db.query(MediaAsset).filter(MediaAsset.id == data.media_id, MediaAsset.project_id == project_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Média non trouvé pour ce projet")
    # Exécution moteur de règles §8.3 (pure Python, sans modèle IA)
    engine = RythmoEngine()
    # Pour la démonstration, on simule des mots depuis des segments transcrits du media
    # En production : récupération des Word + TranscriptSegment liés
    from app.models import Word, TranscriptSegment
    words = db.query(Word).filter(Word.segment_id.in_(
        db.query(TranscriptSegment.id).filter(TranscriptSegment.media_id == media.id).subquery()
    )).order_by(Word.start_ms).all()
    word_dicts = [{"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms, "speaker_id": w.speaker_id} for w in words]
    if not word_dicts:
        # Si aucun mot transcrit, créer un réplique minimale au moins
        word_dicts = [{"text": "...", "start_ms": 0, "end_ms": 1000, "speaker_id": None}]
    replicas = engine.segment_words(word_dicts)
    for r in replicas:
        db.add(Replica(
            id=uuid.uuid4(),
            media_id=media.id,
            text=r["text"],
            start_ms=r["start_ms"],
            end_ms=r["end_ms"],
            speaker_id=r.get("speaker_id"),
            confidence_score=0.85,
            is_manually_edited=False,
            breath_marker=r.get("has_breath_marker", False),
            order_index=len(db.query(Replica).filter(Replica.media_id == media.id).all()),
        ))
    db.commit()
    return {"project_id": str(project_id), "replica_count": len(replicas), "status": "Prêt pour édition"}
@router.get("/projects/{project_id}/replicas", response_model=list)
def list_replicas(project_id: uuid.UUID, db: Session = Depends(get_db)):
    from app.api.v1.replicas import list_replicas as list_rep
    return list_rep(project_id, db)
