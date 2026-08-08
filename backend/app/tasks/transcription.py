import os
import uuid
import subprocess
from celery import Celery
from faster_whisper import WhisperModel

celery_app = Celery("rythmoai", broker="redis://localhost:6379/0")

MODEL_NAME = os.getenv("WHISPER_MODEL", "large-v3")

# Détection GPU pour bascule CPU / CUDA (§8.4)
def _get_device_and_compute():
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"

@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def transcribe_audio(self, media_path: str, media_id: str):
    """Transcription Whisper Large v3 (§8.2.1) — découpage chunks 30s, langage FR."""
    device, compute_type = _get_device_and_compute()
    # Chargement du modèle self-hosted / CTranslate2
    model = WhisperModel(MODEL_NAME, device=device, compute_type=compute_type)

    segments, info = model.transcribe(
        media_path,
        beam_size=5,
        language="fr",
        task="transcribe",
        condition_on_previous_text=True,
    )

    from sqlalchemy.orm import Session
    from app.core.database import SessionLocal
    from app.models import TranscriptSegment

    db = SessionLocal()
    try:
        for seg in segments:
            db.add(TranscriptSegment(
                id=uuid.uuid4(),
                media_id=uuid.UUID(media_id),
                text=seg.text,
                start_ms=int(seg.start * 1000),
                end_ms=int(seg.end * 1000),
                language=info.language or "fr",
                confidence_score=float(getattr(seg, "avg_logprob", getattr(seg, "confidence", 0.92))),
            ))
        db.commit()
    finally:
        db.close()

    return {"media_id": media_id, "language": info.language, "segments_count": len(segments)}
