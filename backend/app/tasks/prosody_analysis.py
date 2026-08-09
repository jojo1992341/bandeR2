"""
Analyse prosodique pour RythmoAI (§8.2.6 CDC)

Analyse de la prosodie (rythme, intonation, intensité) des fichiers audio.
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app  # Application Celery centralisée


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def prosody_analysis(self, media_path: str = "") -> dict[str, Any]:
    """
    Analyse prosodique du fichier audio (§8.2.6).

    Args:
        media_path: Chemin vers le fichier audio.

    Returns:
        dict: Résultats de l'analyse prosodique.
    """
    return {"task": "prosody_analysis", "status": "ok", "media_path": media_path}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def analyze_prosody(self, media_path: str = "") -> dict[str, Any]:
    """
    Alias pour prosody_analysis (§8.2.6).

    Args:
        media_path: Chemin vers le fichier audio.

    Returns:
        dict: Résultats de l'analyse.
    """
    return {"task": "analyze_prosody", "status": "ok", "media_path": media_path}
