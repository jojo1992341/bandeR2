"""
Orchestration de traitement déclenchée par l'API publique §25.4.

Permet à un client externe (ERP/plateforme de droits) de lancer le pipeline
RythmoAI sur un média préalablement importé, puis de recevoir une notification
webhook à la complétion. Les exports automatiques sont également supportés.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models import Export, MediaAsset, PipelineJob, Project
from app.services import public_api_service

logger = logging.getLogger("rythmoai")

PIPELINE_STATUSES = {
    "pending": "pending",
    "processing": "processing",
    "completed": "completed",
    "failed": "failed",
}


def _get_media(
    db: Session, project_id: uuid.UUID, media_id: Optional[uuid.UUID]
) -> MediaAsset:
    query = db.query(MediaAsset).filter(MediaAsset.project_id == project_id)
    if media_id is not None:
        media = query.filter(MediaAsset.id == media_id).first()
    else:
        media = query.order_by(MediaAsset.created_at.desc()).first()
    if not media:
        raise ValueError("Aucun média trouvé pour ce projet")
    return media


def create_processing_job(
    db: Session,
    project_id: uuid.UUID,
    media_id: Optional[uuid.UUID],
    options: Dict[str, Any],
    triggered_by: Optional[str] = None,
) -> PipelineJob:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("Projet introuvable")
    _get_media(db, project_id, media_id)

    job = PipelineJob(
        id=uuid.uuid4(),
        project_id=project_id,
        status="pending",
        progress_percent=0,
        current_step="queued",
    )
    # Compléments optionnels (les colonnes peuvent ne pas exister sur des anciens schémas)
    try:
        setattr(job, "options", options or {})
        setattr(job, "triggered_by", triggered_by)
        setattr(job, "started_at", datetime.now(timezone.utc))
    except Exception:
        pass
    db.add(job)
    project.status = "En_traitement"
    db.commit()
    db.refresh(job)
    return job


def _update_job(db: Session, job: PipelineJob, **fields) -> None:
    for key, value in fields.items():
        try:
            setattr(job, key, value)
        except Exception:
            pass
    db.commit()
    db.refresh(job)


def run_processing_job(
    job_id: str, project_id: str, media_id: str, options: Dict[str, Any]
) -> None:
    """Exécute la chaîne de pipeline. Prévu pour tourner en tâche de fond."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.query(PipelineJob).filter(PipelineJob.id == uuid.UUID(job_id)).first()
        if not job:
            return
        _update_job(
            db, job, status="processing", current_step="extraction", progress_percent=10
        )

        project = db.query(Project).filter(Project.id == uuid.UUID(project_id)).first()
        media = (
            db.query(MediaAsset).filter(MediaAsset.id == uuid.UUID(media_id)).first()
        )
        if not project or not media:
            raise RuntimeError("Projet ou média introuvable")

        from app.tasks.pipeline import (
            pipeline_extract_normalize,
            pipeline_transcribe_diarize,
            pipeline_generate_rythmo,
            notify_completion,
        )

        pipeline_options = dict(options or {})
        res1 = pipeline_extract_normalize.run(
            media_path=media.storage_path,
            media_id=str(media.id),
            pipeline_options=pipeline_options,
        )
        _update_job(db, job, current_step="transcription", progress_percent=35)

        res2 = pipeline_transcribe_diarize.run(pipeline_result=res1)
        # La tâche de transcription est défensive (fallback) : si l'échec a
        # été journalisé, on propage pour notifier l'intégration via webhook.
        transcription = res2.get("transcription") if isinstance(res2, dict) else None
        if isinstance(transcription, dict) and transcription.get("status") in (
            "fallback_error",
            "error",
        ):
            raise RuntimeError(
                transcription.get("error") or "Échec de l'étape de transcription"
            )
        _update_job(db, job, current_step="generation_rythmo", progress_percent=70)

        merged = {**res1, **res2, "project_id": str(project.id)}
        res3 = pipeline_generate_rythmo.run(pipeline_result=merged)
        _update_job(db, job, current_step="finalisation", progress_percent=90)

        res4 = notify_completion.run(pipeline_result={**merged, **res3})
        if res4.get("status") != "completed":
            raise RuntimeError("Échec de la finalisation du pipeline")

        _update_job(
            db,
            job,
            status="completed",
            progress_percent=100,
            current_step="completed",
            completed_at=datetime.now(timezone.utc),
            error_message=None,
        )

        # Webhook pipeline.completed (§25.4)
        webhook_data = {
            "project_id": str(project.id),
            "media_id": str(media.id),
            "job_id": str(job.id),
            "status": "completed",
            "progress_percent": 100,
            "rythmo_status": (
                res3.get("rythmo_status") if isinstance(res3, dict) else None
            ),
            "auto_export": None,
        }

        if options.get("auto_export"):
            export_format = options.get("export_format", "srt")
            export = _trigger_auto_export(db, project, media, export_format)
            webhook_data["auto_export"] = {
                "export_id": str(export.id),
                "format": export.format,
                "status": export.status,
                "download_url": f"/api/v1/exports/{export.id}/download",
            }
            public_api_service.dispatch_event(
                db,
                project.studio_id,
                "export.completed",
                {
                    "project_id": str(project.id),
                    "export_id": str(export.id),
                    "format": export.format,
                    "status": export.status,
                    "download_url": f"/api/v1/exports/{export.id}/download",
                },
            )

        public_api_service.dispatch_event(
            db,
            project.studio_id,
            "pipeline.completed",
            webhook_data,
        )
    except Exception as exc:
        logger.exception("run_processing_job failed: %s", exc)
        try:
            job = (
                db.query(PipelineJob)
                .filter(PipelineJob.id == uuid.UUID(job_id))
                .first()
            )
            if job:
                _update_job(
                    db,
                    job,
                    status="failed",
                    current_step="failed",
                    error_message=str(exc)[:1000],
                    completed_at=datetime.now(timezone.utc),
                )
                project = (
                    db.query(Project)
                    .filter(Project.id == uuid.UUID(project_id))
                    .first()
                )
                if project:
                    public_api_service.dispatch_event(
                        db,
                        project.studio_id,
                        "pipeline.failed",
                        {
                            "project_id": project_id,
                            "media_id": media_id,
                            "job_id": job_id,
                            "status": "failed",
                            "error": str(exc)[:1000],
                        },
                    )
        except Exception:
            logger.exception("Impossible de notifier l'échec du pipeline")
    finally:
        db.close()


def _trigger_auto_export(
    db: Session, project: Project, media: MediaAsset, export_format: str
) -> Export:
    export = Export(
        id=uuid.uuid4(),
        project_id=project.id,
        format=export_format,
        status="pending",
        created_by="public_api",
        creator_role="client_externe",
        is_watermarked=False,
        is_archived=False,
    )
    db.add(export)
    db.commit()
    db.refresh(export)

    from app.api.v1 import exports as exports_module

    exports_module._generate_export_task(str(export.id), str(project.id))
    db.refresh(export)
    return export
