import uuid
from celery import Celery

celery_app = Celery("rythmoai", broker="redis://localhost:6379/0")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def detect_emotions(self, media_id: str = None, project_id: str = None, replica_id: str = None, **kwargs):
    """
    Tâche Celery §8.2.5 — Détection double analyse acoustique + textuelle
    Produit des EmotionTag pour chaque réplique, n'altère jamais Replica.text
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
def analyze_prosody_emotion(self, media_path: str = "", text: str = "", **kwargs):
    # alias pour compatibilité pipeline legacy §8.2.5
    return detect_emotions.run(media_id=kwargs.get("media_id"), project_id=kwargs.get("project_id"), replica_id=kwargs.get("replica_id"))
