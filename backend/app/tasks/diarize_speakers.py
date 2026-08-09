"""
Diarisation des locuteurs pour RythmoAI (§8.2.4 CDC)

Identification et séparation des locuteurs dans un fichier audio.
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app  # Application Celery centralisée


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def diarize_speakers(self, media_path: str = "") -> dict[str, Any]:
    """
    Diarisation des locuteurs (§8.2.4).

    Args:
        media_path: Chemin vers le fichier audio.

    Returns:
        dict: Résultats de la diarisation.
    """
    return {"task": "diarize_speakers", "status": "ok", "media_path": media_path}
