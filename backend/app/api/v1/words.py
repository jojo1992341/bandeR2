"""
API Words §8.5 — Recalage de mots (forced alignment correction)
PATCH /words/{word_id} pour corriger start_ms / end_ms / speaker_id
Journalisation anonymisée si consentement studio.
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.database import get_db
from app.core.rbac import get_current_user_payload
from app.models import Word, TranscriptSegment, MediaAsset, Project

router = APIRouter(dependencies=[Depends(get_current_user_payload)])

class WordPatchIn(BaseModel):
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    speaker_id: Optional[uuid.UUID] = None
    text: Optional[str] = None

def _serialize_word(w: Word) -> dict:
    return {
        "id": str(w.id),
        "segment_id": str(w.segment_id),
        "text": w.text,
        "start_ms": w.start_ms,
        "end_ms": w.end_ms,
        "speaker_id": str(w.speaker_id) if w.speaker_id else None,
        "language": w.language,
        "confidence_score": float(w.confidence_score) if w.confidence_score is not None else None,
    }

@router.get("/words/{word_id}", response_model=dict)
def get_word(word_id: uuid.UUID, db: Session = Depends(get_db)):
    w = db.query(Word).filter(Word.id == word_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Mot non trouvé")
    return _serialize_word(w)

@router.patch("/words/{word_id}", response_model=dict)
def patch_word(
    word_id: uuid.UUID,
    data: WordPatchIn,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    w = db.query(Word).filter(Word.id == word_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Mot non trouvé")

    # Récupérer le studio pour le consentement
    seg = db.query(TranscriptSegment).filter(TranscriptSegment.id == w.segment_id).first()
    media = db.query(MediaAsset).filter(MediaAsset.id == seg.media_id).first() if seg else None
    project = db.query(Project).filter(Project.id == media.project_id).first() if media else None
    studio_id = project.studio_id if project else None

    # Sauvegarder l'état original pour le feedback
    original = {
        "word_id": str(w.id),
        "start_ms": w.start_ms,
        "end_ms": w.end_ms,
        "speaker_id": str(w.speaker_id) if w.speaker_id else None,
        "text": w.text,
        "text_length": len(w.text or ""),
        "confidence_score": float(w.confidence_score) if w.confidence_score is not None else None,
    }

    # Validation
    new_start = data.start_ms if data.start_ms is not None else w.start_ms
    new_end = data.end_ms if data.end_ms is not None else w.end_ms
    if new_start is not None and new_end is not None and new_start >= new_end:
        raise HTTPException(status_code=422, detail="start_ms doit être < end_ms")

    # Appliquer
    if data.start_ms is not None:
        w.start_ms = data.start_ms
    if data.end_ms is not None:
        w.end_ms = data.end_ms
    if data.speaker_id is not None:
        w.speaker_id = data.speaker_id
    if data.text is not None:
        w.text = data.text

    db.commit()
    db.refresh(w)

    # §8.5 — Journalisation anonymisée si consentement
    try:
        if studio_id:
            from app.services.feedback_service import FeedbackService
            svc = FeedbackService(db)
            if svc.has_consent(studio_id):
                # Déterminer le type
                user_id = None
                if payload and payload.get("sub"):
                    try:
                        user_id = uuid.UUID(payload.get("sub"))
                    except:
                        pass
                # Si start/end a changé -> word_realign
                if data.start_ms is not None or data.end_ms is not None:
                    corrected = {
                        "word_id": str(w.id),
                        "start_ms": w.start_ms,
                        "end_ms": w.end_ms,
                        "text_length": len(w.text or ""),
                        "confidence_score": float(w.confidence_score) if w.confidence_score is not None else None,
                    }
                    svc.log_correction(
                        studio_id=studio_id,
                        correction_type="word_realign",
                        project_id=project.id if project else None,
                        media_id=media.id if media else None,
                        original_data=original,
                        corrected_data=corrected,
                        heuristic_target="prosody",
                        user_id=user_id,
                    )
                # Si speaker a changé -> speaker_correction
                if data.speaker_id is not None and str(data.speaker_id) != original["speaker_id"]:
                    svc.log_correction(
                        studio_id=studio_id,
                        correction_type="speaker_correction",
                        project_id=project.id if project else None,
                        media_id=media.id if media else None,
                        original_data={"speaker_id": original["speaker_id"], "label": ""},
                        corrected_data={"speaker_id": str(w.speaker_id), "num_words_affected": 1},
                        heuristic_target="diarization",
                        user_id=user_id,
                    )
    except Exception as e:
        # Ne jamais bloquer la correction si le feedback échoue
        import logging
        logging.getLogger("rythmoai").warning(f"Feedback log word_realign échoué: {e}")

    return _serialize_word(w)

# Les routes /transcript/segments/{id} et /transcript/words/{id} (correction avec
# RBAC + historique) sont désormais gérées par app.api.v1.transcripts (G-014).

