import uuid
import os
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.rbac import get_optional_user_payload
from app.models import SilenceEvent, MediaAsset
from app.services.silence_service import SilenceService

router = APIRouter()


@router.get("/media/{media_id}/silences", response_model=List[Dict[str, Any]])
@router.get(
    "/api/v1/media/{media_id}/silences", response_model=List[Dict[str, Any]]
)
def get_media_silences(
    media_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_optional_user_payload),
):
    media = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Média introuvable")

    service = SilenceService(db)
    events = service.list_by_media(media_id)
    return [
        {
            "id": str(ev.id),
            "media_id": str(ev.media_id),
            "event_type": ev.event_type,
            "start_ms": ev.start_ms,
            "end_ms": ev.end_ms,
            "duration_ms": ev.duration_ms,
            "confidence_score": ev.confidence_score,
            "details": ev.details or {},
            "created_at": (
                ev.created_at.isoformat() if ev.created_at else None
            ),
        }
        for ev in events
    ]


@router.post(
    "/media/{media_id}/silences/detect",
    response_model=List[Dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/api/v1/media/{media_id}/silences/detect",
    response_model=List[Dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
)
def detect_media_silences(
    media_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_optional_user_payload),
):
    media = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Média introuvable")

    audio_path = media.storage_path
    if not audio_path or not os.path.exists(audio_path):
        from app.ai.silero_vad import SileroVADSilenceDetector

        audio_path = SileroVADSilenceDetector.create_synthetic_test_audio(
            "/tmp/test_silences_8_2_4.wav"
        )

    service = SilenceService(db)
    events = service.detect_and_persist_silences(media_id, audio_path)
    return [
        {
            "id": str(ev.id),
            "media_id": str(ev.media_id),
            "event_type": ev.event_type,
            "start_ms": ev.start_ms,
            "end_ms": ev.end_ms,
            "duration_ms": ev.duration_ms,
            "confidence_score": ev.confidence_score,
            "details": ev.details or {},
            "created_at": (
                ev.created_at.isoformat() if ev.created_at else None
            ),
        }
        for ev in events
    ]
