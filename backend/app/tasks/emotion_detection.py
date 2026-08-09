"""
Détection d'émotions pour RythmoAI (§8.2.5 CDC)

Double analyse acoustique + textuelle pour détection des émotions.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.celery_app import celery_app  # Application Celery centralisée


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def detect_emotions(
    self,
    media_id: str | None = None,
    project_id: str | None = None,
    replica_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Détection double analyse acoustique + textuelle (§8.2.5).

    Produit des EmotionTag pour chaque réplique, n'altère jamais Replica.text.

    Args:
        media_id: ID du média.
        project_id: ID du projet.
        replica_id: ID de la réplique.
        **kwargs: Paramètres optionnels.

    Returns:
        dict: Résultats de la détection.
    """
    from app.core.database import SessionLocal
    from app.services.emotion_service import EmotionService
    from app.models import Replica

    db = SessionLocal()
    try:
        svc = EmotionService(db)

        if replica_id:
            rep = db.query(Replica).filter(Replica.id == uuid.UUID(replica_id)).first()
            if rep:
                tags = svc.analyze_replica(rep)
                return {"replica_id": replica_id, "tags_created": len(tags), "status": "ok"}
            return {"replica_id": replica_id, "tags_created": 0, "status": "not_found"}

        if media_id:
            res = svc.analyze_media_replicas(uuid.UUID(media_id))
            return res

        if project_id:
            res = svc.analyze_project(uuid.UUID(project_id))
            return res

        return {"status": "no_target", "tags_created": 0}
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def analyze_prosody_emotion(
    self,
    media_path: str = "",
    text: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Alias pour compatibilité pipeline legacy §8.2.5.

    Args:
        media_path: Chemin vers le fichier média.
        text: Texte à analyser.
        **kwargs: Paramètres optionnels.

    Returns:
        dict: Résultats de l'analyse.
    """
    return detect_emotions.run(
        media_id=kwargs.get("media_id"),
        project_id=kwargs.get("project_id"),
        replica_id=kwargs.get("replica_id"),
    )
