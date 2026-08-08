import uuid
import os
import subprocess
from celery import Celery
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.config import get_settings
from app.models import TranscriptSegment

celery_app = Celery("rythmoai", broker="redis://localhost:6379/0")

def _ffmpeg_path():
    import shutil
    p = shutil.which("ffmpeg")
    if p is None:
        for c in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
            if os.path.exists(c):
                return c
    return p or "ffmpeg"

def _load_model():
    from faster_whisper import WhisperModel
    model_name = os.getenv("WHISPER_MODEL", "large-v3")
    device = "cuda" if subprocess.run(["nvidia-smi"], capture_output=True).returncode == 0 else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    return WhisperModel(model_name, device=device, compute_type=compute_type)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def forced_alignment(self, media_path: str, segment_id: str = None, language: str = "fr"):
    model = _load_model()
    segments, info = model.transcribe(
        media_path,
        beam_size=5,
        language=language,
        word_timestamps=True,
        task="transcribe",
    )
    db = SessionLocal()
    try:
        for seg in segments:
            db.add(TranscriptSegment(
                id=uuid.uuid4(),
                media_id=uuid.UUID(media_path.split("/")[-2]) if False else None,
                text=seg.text,
                start_ms=int(seg.start * 1000),
                end_ms=int(seg.end * 1000),
                language=info.language or language,
                confidence_score=float(getattr(seg, "avg_logprob", getattr(seg, "confidence", 0.85))),
            ))
        db.commit()
    finally:
        db.close()
    return {"media_path": media_path, "segment_id": segment_id, "language": info.language, "segments_max": len(segments)}
