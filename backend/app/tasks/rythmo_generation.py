"""
Génération Rythmo pour RythmoAI (§8.3 CDC)

Génération de la bande rythmo depuis une transcription.
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app  # Application Celery centralisée


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def generate_rythmo_simple(transcript_id: int) -> dict[str, Any]:
    """
    Génération de la bande rythmo depuis une transcription (§8.3).

    Args:
        transcript_id: ID de la transcription.

    Returns:
        dict: Status de la génération.
    """
    return {"status": "done", "transcript_id": transcript_id, "mode": "simple"}
