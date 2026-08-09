"""
Diarisation pour RythmoAI (§8.2.4 CDC)

Module de diarisation des locuteurs.
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app  # Application Celery centralisée


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def diarize_task(audio_path: str) -> dict[str, Any]:
    """
    Diarisation des locuteurs (§8.2.4).

    Args:
        audio_path: Chemin vers le fichier audio.

    Returns:
        dict: Liste des locuteurs identifiés.
    """
    return {"speakers": [], "audio_path": audio_path}
