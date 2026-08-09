"""
Ressource Transcript (CDC §10.2) — G-014.

Endpoints (contrat cohérent) :
- GET   /projects/{project_id}/transcript       → lecture paginée (segments + mots)
- GET   /transcript/segments/{segment_id}        → lecture d'un segment
- PATCH /transcript/segments/{segment_id}        → correction d'un segment
- GET   /transcript/segments/{segment_id}/history→ historique des corrections
- GET   /transcript/words/{word_id}              → lecture d'un mot
- PATCH /transcript/words/{word_id}              → correction d'un mot
- GET   /transcript/words/{word_id}/history      → historique des corrections

Sécurité : RBAC (JWT) + isolation multi-tenant (anti-IDOR §15.7). Chaque
correction est journalisée (`transcript_edit_history`) et marquée
`is_manually_edited` pour permettre de retrouver les modifications.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import get_current_user_payload
from app.core.rls_context import set_studio_context
from app.core.tenant import get_user_id_from_payload, get_user_studio_ids
from app.models import (
    MediaAsset,
    Project,
    TranscriptEditHistory,
    TranscriptSegment,
    Word,
)

router = APIRouter()


# ------------------------------------------------------------------
# Schémas (contrat OpenAPI)
# ------------------------------------------------------------------
class WordOut(BaseModel):
    id: str
    segment_id: str
    text: str
    start_ms: int
    end_ms: int
    speaker_id: Optional[str]
    language: Optional[str]
    confidence_score: Optional[float]
    is_manually_edited: bool


class SegmentOut(BaseModel):
    id: str
    media_id: str
    text: str
    start_ms: int
    end_ms: int
    language: Optional[str]
    confidence_score: Optional[float]
    is_manually_edited: bool
    words: List[WordOut]


class TranscriptResponse(BaseModel):
    project_id: str
    segments: List[SegmentOut]
    total: int
    page: int
    page_size: int


class SegmentPatchIn(BaseModel):
    text: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None


class WordPatchIn(BaseModel):
    text: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    speaker_id: Optional[str] = None


class HistoryOut(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    field: str
    old_value: Optional[str]
    new_value: Optional[str]
    edited_by: Optional[str]
    created_at: datetime


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _serialize_word(w: Word) -> WordOut:
    return WordOut(
        id=str(w.id),
        segment_id=str(w.segment_id),
        text=w.text,
        start_ms=w.start_ms,
        end_ms=w.end_ms,
        speaker_id=str(w.speaker_id) if w.speaker_id else None,
        language=getattr(w, "language", None),
        confidence_score=(
            float(w.confidence_score) if w.confidence_score is not None else None
        ),
        is_manually_edited=bool(getattr(w, "is_manually_edited", False)),
    )


def _serialize_segment(s: TranscriptSegment, words: List[Word]) -> SegmentOut:
    return SegmentOut(
        id=str(s.id),
        media_id=str(s.media_id),
        text=s.text,
        start_ms=s.start_ms,
        end_ms=s.end_ms,
        language=getattr(s, "language", None),
        confidence_score=(
            float(s.confidence_score) if s.confidence_score is not None else None
        ),
        is_manually_edited=bool(getattr(s, "is_manually_edited", False)),
        words=[_serialize_word(w) for w in words],
    )


def _segment_studio_id(db: Session, segment: TranscriptSegment):
    media = (
        db.query(MediaAsset).filter(MediaAsset.id == segment.media_id).first()
    )
    if not media:
        return None
    project = db.query(Project).filter(Project.id == media.project_id).first()
    return project.studio_id if project else None


def _word_studio_id(db: Session, word: Word):
    segment = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.id == word.segment_id)
        .first()
    )
    if not segment:
        return None
    return _segment_studio_id(db, segment)


def _check_tenant(user_studios, studio_id, entity_label: str):
    if studio_id is None or studio_id not in user_studios:
        raise HTTPException(
            status_code=404,
            detail=f"{entity_label} introuvable (§15.7 IDOR protection)",
        )


def _record_history(
    db: Session,
    entity_type: str,
    entity_id: uuid.UUID,
    studio_id: uuid.UUID,
    edited_by: Optional[uuid.UUID],
    changes,
) -> None:
    for field, old, new in changes:
        if old != new:
            db.add(
                TranscriptEditHistory(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    studio_id=studio_id,
                    field=field,
                    old_value=None if old is None else str(old),
                    new_value=None if new is None else str(new),
                    edited_by=edited_by,
                )
            )


def _validate_bounds(start_ms: Optional[int], end_ms: Optional[int]) -> None:
    if (
        start_ms is not None
        and end_ms is not None
        and start_ms >= end_ms
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_ms doit être strictement inférieur à end_ms",
        )


# ------------------------------------------------------------------
# Lecture paginée par projet
# ------------------------------------------------------------------
@router.get("/projects/{project_id}/transcript", response_model=TranscriptResponse)
def get_project_transcript(
    project_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    edited_only: bool = Query(False),
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Transcription paginée d'un projet (segments + mots), anti-IDOR."""
    user_id = get_user_id_from_payload(payload)
    user_studios = get_user_studio_ids(db, user_id)

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or project.studio_id not in user_studios:
        raise HTTPException(
            status_code=404,
            detail="Projet introuvable (§15.7 IDOR protection)",
        )
    set_studio_context(db, project.studio_id)

    media_ids = [
        r[0]
        for r in db.query(MediaAsset.id)
        .filter(MediaAsset.project_id == project.id)
        .all()
    ]
    if not media_ids:
        return TranscriptResponse(
            project_id=str(project.id), segments=[], total=0, page=page, page_size=page_size
        )

    q = db.query(TranscriptSegment).filter(
        TranscriptSegment.media_id.in_(media_ids)
    )
    if edited_only:
        q = q.filter(TranscriptSegment.is_manually_edited.is_(True))
    total = q.count()
    segments = (
        q.order_by(TranscriptSegment.start_ms.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Mots en une seule requête (évite le N+1)
    seg_ids = [s.id for s in segments]
    words = (
        db.query(Word).filter(Word.segment_id.in_(seg_ids)).all()
        if seg_ids
        else []
    )
    words_by_seg: dict = {}
    for w in words:
        words_by_seg.setdefault(w.segment_id, []).append(w)
    for grp in words_by_seg.values():
        grp.sort(key=lambda x: x.start_ms)

    return TranscriptResponse(
        project_id=str(project.id),
        segments=[_serialize_segment(s, words_by_seg.get(s.id, [])) for s in segments],
        total=total,
        page=page,
        page_size=page_size,
    )


# ------------------------------------------------------------------
# Segments
# ------------------------------------------------------------------
def _load_segment_for_user(db, user_id, segment_id):
    segment = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.id == segment_id)
        .first()
    )
    if not segment:
        raise HTTPException(status_code=404, detail="Segment introuvable")
    user_studios = get_user_studio_ids(db, user_id)
    studio_id = _segment_studio_id(db, segment)
    _check_tenant(user_studios, studio_id, "Segment")
    set_studio_context(db, studio_id)
    return segment, studio_id


@router.get("/transcript/segments/{segment_id}", response_model=SegmentOut)
def get_segment(
    segment_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    segment, _ = _load_segment_for_user(db, user_id, segment_id)
    words = db.query(Word).filter(Word.segment_id == segment.id).all()
    return _serialize_segment(segment, words)


@router.patch("/transcript/segments/{segment_id}", response_model=SegmentOut)
def patch_segment(
    segment_id: uuid.UUID,
    data: SegmentPatchIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    segment, studio_id = _load_segment_for_user(db, user_id, segment_id)

    _validate_bounds(
        data.start_ms if data.start_ms is not None else segment.start_ms,
        data.end_ms if data.end_ms is not None else segment.end_ms,
    )

    changes = []
    if data.text is not None and data.text != segment.text:
        changes.append(("text", segment.text, data.text))
        segment.text = data.text
    if data.start_ms is not None and data.start_ms != segment.start_ms:
        changes.append(("start_ms", segment.start_ms, data.start_ms))
        segment.start_ms = data.start_ms
    if data.end_ms is not None and data.end_ms != segment.end_ms:
        changes.append(("end_ms", segment.end_ms, data.end_ms))
        segment.end_ms = data.end_ms

    if changes:
        segment.is_manually_edited = True
        _record_history(db, "segment", segment.id, studio_id, user_id, changes)

    db.commit()
    db.refresh(segment)
    words = db.query(Word).filter(Word.segment_id == segment.id).all()
    return _serialize_segment(segment, words)


@router.get(
    "/transcript/segments/{segment_id}/history", response_model=List[HistoryOut]
)
def segment_history(
    segment_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    segment, _ = _load_segment_for_user(db, user_id, segment_id)
    rows = (
        db.query(TranscriptEditHistory)
        .filter(
            TranscriptEditHistory.entity_type == "segment",
            TranscriptEditHistory.entity_id == segment.id,
        )
        .order_by(TranscriptEditHistory.created_at.desc())
        .all()
    )
    return [_serialize_history(r) for r in rows]


# ------------------------------------------------------------------
# Mots
# ------------------------------------------------------------------
def _load_word_for_user(db, user_id, word_id):
    word = db.query(Word).filter(Word.id == word_id).first()
    if not word:
        raise HTTPException(status_code=404, detail="Mot introuvable")
    user_studios = get_user_studio_ids(db, user_id)
    studio_id = _word_studio_id(db, word)
    _check_tenant(user_studios, studio_id, "Mot")
    set_studio_context(db, studio_id)
    return word, studio_id


@router.get("/transcript/words/{word_id}", response_model=WordOut)
def get_word(
    word_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    word, _ = _load_word_for_user(db, user_id, word_id)
    return _serialize_word(word)


@router.patch("/transcript/words/{word_id}", response_model=WordOut)
def patch_word(
    word_id: uuid.UUID,
    data: WordPatchIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    word, studio_id = _load_word_for_user(db, user_id, word_id)

    _validate_bounds(
        data.start_ms if data.start_ms is not None else word.start_ms,
        data.end_ms if data.end_ms is not None else word.end_ms,
    )

    changes = []
    if data.text is not None and data.text != word.text:
        changes.append(("text", word.text, data.text))
        word.text = data.text
    if data.start_ms is not None and data.start_ms != word.start_ms:
        changes.append(("start_ms", word.start_ms, data.start_ms))
        word.start_ms = data.start_ms
    if data.end_ms is not None and data.end_ms != word.end_ms:
        changes.append(("end_ms", word.end_ms, data.end_ms))
        word.end_ms = data.end_ms
    if data.speaker_id is not None:
        new_sid = data.speaker_id if data.speaker_id else None
        old_sid = str(word.speaker_id) if word.speaker_id else None
        if new_sid != old_sid:
            changes.append(("speaker_id", old_sid, new_sid))
            word.speaker_id = uuid.UUID(new_sid) if new_sid else None

    if changes:
        word.is_manually_edited = True
        _record_history(db, "word", word.id, studio_id, user_id, changes)

    db.commit()
    db.refresh(word)
    return _serialize_word(word)


@router.get("/transcript/words/{word_id}/history", response_model=List[HistoryOut])
def word_history(
    word_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    word, _ = _load_word_for_user(db, user_id, word_id)
    rows = (
        db.query(TranscriptEditHistory)
        .filter(
            TranscriptEditHistory.entity_type == "word",
            TranscriptEditHistory.entity_id == word.id,
        )
        .order_by(TranscriptEditHistory.created_at.desc())
        .all()
    )
    return [_serialize_history(r) for r in rows]


def _serialize_history(h: TranscriptEditHistory) -> HistoryOut:
    return HistoryOut(
        id=str(h.id),
        entity_type=h.entity_type,
        entity_id=str(h.entity_id),
        field=h.field,
        old_value=h.old_value,
        new_value=h.new_value,
        edited_by=str(h.edited_by) if h.edited_by else None,
        created_at=h.created_at,
    )
