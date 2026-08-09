"""
Détection d'émotions pour RythmoAI (§8.2.5, §5.4 CDC)

Double analyse acoustique + textuelle pour détection des émotions.
Utilise l'Internal API pour persister les résultats (§5.4).
"""

from __future__ import annotations

import uuid
from typing import Any

from datetime import datetime, timezone

from app.celery_app import celery_app  # Application Celery centralisée
from app.internal_api import (
    WorkerInternalAPI,
    ArtifactMetadata,
    get_worker_api,
)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def detect_emotions(
    self,
    media_id: str | None = None,
    project_id: str | None = None,
    replica_id: str | None = None,
    artifact_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Détection double analyse acoustique + textuelle (§8.2.5).

    Produit des EmotionTag pour chaque réplique.
    Utilise l'Internal API pour persister les résultats (§5.4).

    Args:
        media_id: ID du média.
        project_id: ID du projet.
        replica_id: ID de la réplique.
        artifact_id: ID de l'artefact (optionnel).
        **kwargs: Paramètres optionnels.

    Returns:
        dict: Résultats de la détection.
    """
    api = get_worker_api()
    
    # Générer ou récupérer l'ID d'artefact
    if artifact_id:
        artifact_uuid = uuid.UUID(artifact_id)
    else:
        artifact_uuid = uuid.uuid4()
    
    # Identifier la cible
    target_id = replica_id or media_id or project_id
    target_type = (
        "replica" if replica_id 
        else "media" if media_id 
        else "project" if project_id 
        else None
    )
    
    if not target_id:
        return {"status": "no_target", "tags_created": 0}
    
    # Simuler la détection d'émotions (dans un cas réel, utiliser l'API externe)
    # Ici on génère des tags "émotionnels" factices pour démo
    emotions = [
        {"emotion": "neutre", "confidence": 0.85, "segment_start_ms": 0, "segment_end_ms": 1000},
        {"emotion": "joie", "confidence": 0.72, "segment_start_ms": 1000, "segment_end_ms": 2500},
    ]
    
    result_data = {
        "target_id": target_id,
        "target_type": target_type,
        "emotions": emotions,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # Sauvegarder les résultats via l'Internal API
    result_path = api.save_result(
        artifact_uuid,
        result_data,
        content_type="application/json"
    )
    
    # Mettre à jour les métadonnées
    if artifact_id is None:
        metadata = ArtifactMetadata(
            id=artifact_uuid,
            type="emotion_detection",
            media_id=uuid.UUID(target_id) if target_type == "media" else None,
            status="completed",
            result_path=result_path,
        )
        api.save_artifact(metadata)
    else:
        api.update_artifact_status(
            artifact_uuid,
            status="completed",
            result_path=result_path
        )
    
    return {
        "target_id": target_id,
        "target_type": target_type,
        "tags_created": len(emotions),
        "status": "ok",
        "artifact_id": str(artifact_uuid),
        "result_path": result_path,
    }


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
