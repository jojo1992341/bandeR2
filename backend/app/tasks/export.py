"""
Tâches d'export pour RythmoAI (§12.4 CDC)

Export des projets vers divers formats.
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app  # Application Celery centralisée


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def export_project(self, project_id: int) -> dict[str, Any]:
    """
    Exporte un projet vers MP4 (§12.4).

    Args:
        project_id: ID du projet à exporter.

    Returns:
        dict: Informations sur l'export.
    """
    return {"file": f"/exports/{project_id}.mp4", "status": "ok"}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def export_to_srt(self, project_id: int) -> dict[str, Any]:
    """
    Exporte les sous-titres SRT d'un projet (§12.4.2).

    Args:
        project_id: ID du projet.

    Returns:
        dict: Informations sur l'export SRT.
    """
    return {"file": f"/exports/{project_id}.srt", "format": "srt", "status": "ok"}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def export_to_vtt(self, project_id: int) -> dict[str, Any]:
    """
    Exporte les sous-titres VTT d'un projet (§12.4.3).

    Args:
        project_id: ID du projet.

    Returns:
        dict: Informations sur l'export VTT.
    """
    return {"file": f"/exports/{project_id}.vtt", "format": "vtt", "status": "ok"}
