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
from app.core.rbac import get_current_user_payload, _get_user_id, assert_studio_member
from app.models import Word, TranscriptSegment, MediaAsset, Project

router = APIRouter()

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
def get_word(word_id: uuid.UUID, db: Session = Depends(get_db), payload: dict = Depends(get_current_user_payload)):
    _uid = _get_user_id(payload)
    from app.models import Word as _W, TranscriptSegment as _TS, MediaAsset as _MA, Project as _PR
    _w = db.query(_W).filter(_W.id == word_id).first()
    if _w and _w.segment_id:
        seg = db.query(_TS).filter(_TS.id == _w.segment_id).first()
        if seg and seg.media_id:
            med = db.query(_MA).filter(_MA.id == seg.media_id).first()
            if med:
                proj = db.query(_PR).filter(_PR.id == med.project_id).first()
                if proj:
                    assert_studio_member(db, _uid, proj.studio_id)
    w = db.query(Word).filter(Word.id == word_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Mot non trouvé")
    return _serialize_word(w)

@router.patch("/words/{word_id}", response_model=dict)
def patch_word(
    word_id: uuid.UUID,
    data: WordPatchIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user_payload),
):
    w = db.query(Word).filter(Word.id == word_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Mot non trouvé")

    # Récupérer le studio pour le consentement
    seg = db.query(TranscriptSegment).filter(TranscriptSegment.id == w.segment_id).first()
    media = db.query(MediaAsset).filter(MediaAsset.id == seg.media_id).first() if seg else None
    project = db.query(Project).filter(Project.id == media.project_id).first() if media else None
    studio_id = project.studio_id if project else None
    if studio_id:
        _uid_w = _get_user_id(payload)
        assert_studio_member(db, _uid_w, studio_id)

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

@router.patch("/transcript/words/{word_id}", response_model=dict)
def patch_word_alias(word_id: uuid.UUID, data: WordPatchIn, db: Session = Depends(get_db), payload: dict = Depends(get_current_user_payload)):
    return patch_word(word_id, data, db, payload)

# Aussi exposer le patch pour les segments (au cas où)
class SegmentPatchIn(BaseModel):
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    text: Optional[str] = None

@router.patch("/transcript/segments/{segment_id}", response_model=dict)
def patch_segment(segment_id: uuid.UUID, data: SegmentPatchIn, db: Session = Depends(get_db), payload: dict = Depends(get_current_user_payload)):
    seg = db.query(TranscriptSegment).filter(TranscriptSegment.id == segment_id).first()
    if seg:
        _med = db.query(MediaAsset).filter(MediaAsset.id == seg.media_id).first()
        if _med:
            _proj = db.query(Project).filter(Project.id == _med.project_id).first()
            if _proj:
                assert_studio_member(db, _get_user_id(payload), _proj.studio_id)
    if not seg:
        raise HTTPException(status_code=404, detail="Segment non trouvé")
    if data.text is not None:
        seg.text = data.text
    if data.start_ms is not None:
        seg.start_ms = data.start_ms
    if data.end_ms is not None:
        seg.end_ms = data.end_ms
    db.commit()
    db.refresh(seg)
    return {
        "id": str(seg.id),
        "media_id": str(seg.media_id),
        "text": seg.text,
        "start_ms": seg.start_ms,
        "end_ms": seg.end_ms,
        "language": seg.language,
        "confidence_score": float(seg.confidence_score) if seg.confidence_score is not None else None,
    }
