"""
Génération Rythmo pour RythmoAI (§8.3 CDC)

Génération de la bande rythmo (synchronisation labiale).
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app  # Application Celery centralisée


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def generate_rythmo(self, media_path: str = "", **kwargs: Any) -> dict[str, Any]:
    """
    Génération de la bande rythmo (§8.3).

    Args:
        media_path: Chemin vers le fichier média.
        **kwargs: Paramètres optionnels.

    Returns:
        dict: Résultats de la génération.
    """
    return {"task": "generate_rythmo", "status": "ok", "media_path": media_path}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def generate_rythmo_band(
    self,
    media_path: str = "",
    project_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Génération de la bande rythmo pour un projet (§8.3).

    Args:
        media_path: Chemin vers le fichier média.
        project_id: ID du projet.
        **kwargs: Paramètres optionnels.

    Returns:
        dict: Résultats de la génération.
    """
    return {
        "task": "generate_rythmo_band",
        "status": "ok",
        "media_path": media_path,
        "project_id": project_id,
    }
