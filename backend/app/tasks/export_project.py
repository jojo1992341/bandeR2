"""
Tâches d'export project pour RythmoAI (§12.4 CDC)

Ce module est maintenu pour compatibilité ascendante.
Les exports sont maintenant centralisés dans app.tasks.export.
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app  # Application Celery centralisée


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def export_project_legacy(self, media_path: str = "") -> dict[str, Any]:
    """
    Export legacy (maintenu pour compatibilité).
    Préférer app.tasks.export.export_project pour le nouveau code.

    Args:
        media_path: Chemin vers le média.

    Returns:
        dict: Status de l'export.
    """
    return {"task": "export_project_legacy", "status": "ok", "media_path": media_path}
