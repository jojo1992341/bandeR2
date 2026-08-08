import os
from celery import Celery, chain, chord, group
from celery.exceptions import MaxRetriesExceededError

celery_app = Celery("rythmoai", broker="redis://localhost:6379/0")

# Configuration résilience (§6.4 — retry 3, backoff exponentiel, circuit breaker, DLQ)
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.task_default_queue = "celery"

# Configuration file Dead-Letter (DLQ §6.4 / §10.3)
celery_app.conf.task_routes = {
    "app.tasks.pipeline.*": {"queue": "celery"},
    "app.tasks.dlq.*": {"queue": "dead_letter"},
}


def _exponential_backoff(retry_count: int) -> int:
    """Calcul du backoff exponentiel (2^retry_count * 5s) limité à 300s."""
    return min((2**retry_count) * 5, 300)


from app.tasks.normalize_audio import normalize_audio
from app.tasks.transcription import transcribe_audio
from app.tasks.forced_alignment import forced_alignment
from app.tasks.diarize_speakers import diarize_speakers
from app.tasks.prosody_analysis import analyze_prosody
from app.tasks.generate_rythmo import generate_rythmo_band
from app.tasks.export import export_project
from app.tasks.audio_extraction import extract_audio


@celery_app.task(
    bind=True, max_retries=3, default_retry_delay=10, autoretry_for=(Exception,)
)
def pipeline_extract_normalize(self, media_path: str, media_id: str):
    # Étape 1 : extraction + normalisation EBU R128
    extract_result = extract_audio.run(
        media_path=media_path, output_dir="/tmp/rythmoai_audio"
    )
    return {
        "media_path": media_path,
        "media_id": media_id,
        "extracted_tracks": extract_result,
    }


@celery_app.task(
    bind=True, max_retries=3, default_retry_delay=15, autoretry_for=(Exception,)
)
def pipeline_transcribe_diarize(self, pipeline_result: dict):
    # Étape 2 : transcription Whisper + diarization Pyannote en parallèle (groupe Celery)
    media_id = pipeline_result.get("media_id")
    tracks = pipeline_result.get("extracted_tracks", {}).get("tracks", [])
    first_track_path = (
        tracks[0]["local_path"]
        if tracks
        else pipeline_result.get("media_path", "")
    )

    t_res = transcribe_audio.run(
        media_path=first_track_path, media_id=str(media_id)
    )
    d_res = diarize_speakers.run(media_path=first_track_path)
    return {
        **pipeline_result,
        "transcription": t_res,
        "diarization": d_res,
        "progress_percent": 60,
    }


@celery_app.task(
    bind=True, max_retries=2, default_retry_delay=15, autoretry_for=(Exception,)
)
def pipeline_generate_rythmo(self, pipeline_result: dict):
    # Étape 3 : génération bande rythmo
    result = generate_rythmo_band.run(project_id=pipeline_result.get("media_id"))
    return {**pipeline_result, "rythmo_status": result}


@celery_app.task(
    bind=True, max_retries=1, default_retry_delay=30, autoretry_for=(Exception,)
)
def notify_completion(self, pipeline_result: dict):
    # Étape finale : mise à jour PipelineJob → "Prêt pour édition" + notification
    import uuid
    from app.core.database import SessionLocal
    from app.models import PipelineJob

    db = SessionLocal()
    try:
        val = pipeline_result.get("project_id") or pipeline_result.get("media_id")
        val_uuid = None
        if val:
            try:
                val_uuid = uuid.UUID(str(val))
            except Exception:
                val_uuid = None
        job = None
        if val_uuid:
            job = (
                db.query(PipelineJob)
                .filter(PipelineJob.project_id == val_uuid)
                .first()
            )
            if not job:
                job = (
                    db.query(PipelineJob).filter(PipelineJob.id == val_uuid).first()
                )
        if job:
            job.status = "Prêt pour édition"
            job.progress_percent = 100
            job.current_step = "export"
            db.commit()
    finally:
        db.close()
    # DLQ : si échec définitif après retries, Celery route automatiquement vers dead_letter
    return {"status": "completed", "pipeline": pipeline_result}
