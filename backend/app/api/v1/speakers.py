import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.auth_handler import verify_token
from app.core.rbac import require_role
from app.models import Speaker, Project

router = APIRouter()

class SpeakerMergeIn(BaseModel):
    label: str | None = None
    merge_into: uuid.UUID | None = None

@router.get("/projects/{project_id}/speakers")
def list_speakers(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.query(Speaker).filter(Speaker.project_id == project_id).all()

@router.patch("/speakers/{speaker_id}")
def patch_speaker(speaker_id: uuid.UUID, data: SpeakerMergeIn, db: Session = Depends(get_db)):
    speaker = db.query(Speaker).filter(Speaker.id == speaker_id).first()
    if not speaker:
        raise HTTPException(status_code=404, detail="Locuteur non trouvé")
    if data.label:
        speaker.label = data.label
    if data.merge_into:
        # Fusion : transférer mots du speaker supprimé vers le cible
        from app.models import Word
        words = db.query(Word).filter(Word.speaker_id == speaker_id).all()
        for w in words:
            w.speaker_id = data.merge_into
        db.delete(speaker)
    db.commit()
    db.refresh(speaker) if speaker else None
    return {"id": str(speaker.id), "label": speaker.label, "merged": data.merge_into is not None}
