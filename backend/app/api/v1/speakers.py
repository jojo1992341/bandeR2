import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.auth_handler import verify_token
from app.core.rbac import require_role, get_current_user_payload
from app.models import Speaker, Project
import uuid
from typing import Optional

router = APIRouter(dependencies=[Depends(get_current_user_payload)])

class SpeakerMergeIn(BaseModel):
    label: str | None = None
    merge_into: uuid.UUID | None = None

@router.get("/projects/{project_id}/speakers")
def list_speakers(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.query(Speaker).filter(Speaker.project_id == project_id).all()

@router.patch("/speakers/{speaker_id}")
def patch_speaker(speaker_id: uuid.UUID, data: SpeakerMergeIn, db: Session = Depends(get_db), payload: Optional[dict] = Depends(get_current_user_payload)):
    speaker = db.query(Speaker).filter(Speaker.id == speaker_id).first()
    if not speaker:
        raise HTTPException(status_code=404, detail="Locuteur non trouvé")
    # Sauvegarder l'état original pour feedback
    _orig_label = speaker.label
    _orig_id = speaker.id
    project = db.query(Project).filter(Project.id == speaker.project_id).first()
    studio_id = project.studio_id if project else None
    _orig_speaker_count = 0
    if data.merge_into:
        from app.models import Word
        _orig_speaker_count = db.query(Word).filter(Word.speaker_id == speaker_id).count()
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
    if speaker and not data.merge_into:
        try:
            db.refresh(speaker)
        except:
            pass
    # §8.5 — Journalisation anonymisée si consentement
    try:
        if studio_id:
            from app.services.feedback_service import FeedbackService
            svc = FeedbackService(db)
            if svc.has_consent(studio_id):
                user_id = None
                if payload and payload.get("sub"):
                    try:
                        user_id = uuid.UUID(payload.get("sub"))
                    except:
                        pass
                if data.merge_into:
                    # Fusion = correction de locuteur (diarization)
                    # Utiliser project.id (pas project.project_id) et _orig_id
                    _proj_id = project.id if project else None
                    svc.log_correction(
                        studio_id=studio_id,
                        correction_type="speaker_correction",
                        project_id=_proj_id,
                        original_data={"speaker_id": str(_orig_id), "label": _orig_label},
                        corrected_data={"speaker_id": str(data.merge_into), "num_words_affected": _orig_speaker_count},
                        heuristic_target="diarization",
                        user_id=user_id,
                    )
                elif data.label and data.label != _orig_label:
                    _proj_id2 = project.id if project else speaker.project_id
                    svc.log_correction(
                        studio_id=studio_id,
                        correction_type="speaker_correction",
                        project_id=_proj_id2,
                        original_data={"speaker_id": str(_orig_id), "label": _orig_label},
                        corrected_data={"speaker_id": str(_orig_id), "label": data.label, "num_words_affected": 0},
                        heuristic_target="diarization",
                        user_id=user_id,
                    )
    except Exception as _fb_e:
        import logging
        logging.getLogger("rythmoai").warning(f"Feedback log speaker échoué: {_fb_e}")
    if data.merge_into:
        return {"id": str(_orig_id), "label": _orig_label, "merged": True, "merged_into": str(data.merge_into)}
    return {"id": str(speaker.id), "label": speaker.label, "merged": data.merge_into is not None}
