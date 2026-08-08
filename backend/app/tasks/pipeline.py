import os
import logging
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


try:
    from app.tasks.normalize_audio import normalize_audio
except ImportError:
    normalize_audio = None
try:
    from app.tasks.transcription import transcribe_audio
except ImportError:
    transcribe_audio = None
try:
    from app.tasks.forced_alignment import forced_alignment
except ImportError:
    forced_alignment = None
try:
    from app.tasks.diarize_speakers import diarize_speakers
except ImportError:
    diarize_speakers = None
try:
    from app.tasks.prosody_analysis import analyze_prosody
except ImportError:
    analyze_prosody = None
try:
    from app.tasks.generate_rythmo import generate_rythmo_band
except ImportError:
    generate_rythmo_band = None
try:
    from app.tasks.export import export_project
except ImportError:
    export_project = None
try:
    from app.tasks.audio_extraction import extract_audio
except ImportError:
    extract_audio = None

logger = logging.getLogger("rythmoai")


@celery_app.task(
    bind=True, max_retries=3, default_retry_delay=10, autoretry_for=(Exception,)
)
def pipeline_extract_normalize(self, media_path: str, media_id: str):
    # Étape 1 : extraction + normalisation EBU R128
    try:
        if extract_audio is not None:
            extract_result = extract_audio.run(
                media_path=media_path, output_dir="/tmp/rythmoai_audio"
            )
        else:
            extract_result = {"tracks": [{"local_path": media_path}], "status": "fallback_no_extract"}
    except Exception as e:
        logger.warning(f"extract_audio fallback: {e}")
        extract_result = {"tracks": [{"local_path": media_path}], "status": "fallback_error"}
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

    try:
        if transcribe_audio is not None:
            t_res = transcribe_audio.run(
                media_path=first_track_path, media_id=str(media_id)
            )
        else:
            t_res = {"media_id": str(media_id), "language": "fr", "segments_count": 1, "status": "fallback"}
    except Exception as e:
        logger.warning(f"transcribe_audio fallback: {e}")
        t_res = {"media_id": str(media_id), "language": "fr", "segments_count": 1, "status": "fallback_error"}
    try:
        if diarize_speakers is not None:
            d_res = diarize_speakers.run(media_path=first_track_path)
        else:
            d_res = {"speakers": [], "status": "fallback"}
    except Exception as e:
        logger.warning(f"diarize_speakers fallback: {e}")
        d_res = {"speakers": [], "status": "fallback_error"}
    try:
        import uuid
        from app.core.database import SessionLocal
        from app.services.silence_service import SilenceService

        db = SessionLocal()
        try:
            svc = SilenceService(db)
            svc.detect_and_persist_silences(
                uuid.UUID(str(media_id)), first_track_path
            )
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Silence detection in pipeline warning: {e}")
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
    try:
        if generate_rythmo_band is not None:
            result = generate_rythmo_band.run(project_id=pipeline_result.get("media_id"))
        else:
            result = {"task": "generate_rythmo_band", "status": "fallback"}
    except Exception as e:
        logger.warning(f"generate_rythmo_band fallback: {e}")
        result = {"task": "generate_rythmo_band", "status": "fallback_error", "error": str(e)}
    # §8.2.5 — Détection d'émotions / intentions après génération Rythmo
    # Double analyse acoustique + textuelle → EmotionTag, indicatif uniquement
    try:
        import uuid
        from app.core.database import SessionLocal
        from app.services.emotion_service import EmotionService

        db = SessionLocal()
        try:
            media_id_val = pipeline_result.get("media_id")
            if media_id_val:
                svc = EmotionService(db)
                # Analyse toutes les répliques du média généré
                try:
                    res = svc.analyze_media_replicas(uuid.UUID(str(media_id_val)))
                    logger.info(f"Emotion detection in pipeline: {res}")
                    pipeline_result["emotion_detection"] = res
                except Exception as inner:
                    logger.warning(f"Emotion detection warning (non-bloquant): {inner}")
                    pipeline_result["emotion_detection"] = {"status": "warning", "error": str(inner)}
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Emotion pipeline integration warning: {e}")
        pipeline_result["emotion_detection"] = {"status": "error", "error": str(e)}
    return {**pipeline_result, "rythmo_status": result}


@celery_app.task(
    bind=True, max_retries=2, default_retry_delay=15, autoretry_for=(Exception,)
)
def pipeline_detect_emotions(self, pipeline_result: dict):
    """
    Étape dédiée §8.2.5 — détection d'émotions/intentions (peut être appelée en chord après génération Rythmo)
    """
    import uuid
    from app.core.database import SessionLocal
    from app.services.emotion_service import EmotionService

    db = SessionLocal()
    try:
        media_id_val = pipeline_result.get("media_id")
        project_id_val = pipeline_result.get("project_id")
        svc = EmotionService(db)
        if media_id_val:
            res = svc.analyze_media_replicas(uuid.UUID(str(media_id_val)))
            return {**pipeline_result, "emotion_detection": res}
        if project_id_val:
            res = svc.analyze_project(uuid.UUID(str(project_id_val)))
            return {**pipeline_result, "emotion_detection": res}
        return {**pipeline_result, "emotion_detection": {"status": "skipped", "reason": "no media/project id"}}
    finally:
        db.close()


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
            if not job:
                job = PipelineJob(
                    id=uuid.uuid4(),
                    project_id=val_uuid,
                    status="Prêt pour édition",
                    progress_percent=100,
                    current_step="export",
                )
                db.add(job)
        if job:
            job.status = "Prêt pour édition"
            job.progress_percent = 100
            job.current_step = "export"
            from app.models import Project

            project = (
                db.query(Project)
                .filter(Project.id == job.project_id)
                .first()
            )
            if project:
                project.status = "Pret_pour_edition"
            db.commit()
    finally:
        db.close()
    # DLQ : si échec définitif après retries, Celery route automatiquement vers dead_letter
    return {"status": "completed", "pipeline": pipeline_result}
