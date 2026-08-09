import uuid
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.rbac import get_current_user_payload
from app.models import Replica, MediaAsset, Project, EmotionTag
from app.services.emotion_service import EmotionService

router = APIRouter(dependencies=[Depends(get_current_user_payload)])


@router.get("/replicas/{replica_id}/emotion-tags", response_model=List[Dict[str, Any]])
@router.get("/api/v1/replicas/{replica_id}/emotion-tags", response_model=List[Dict[str, Any]])
def get_replica_emotion_tags(
    replica_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    replica = db.query(Replica).filter(Replica.id == replica_id).first()
    if not replica:
        raise HTTPException(status_code=404, detail="Réplique non trouvée")
    svc = EmotionService(db)
    tags = svc.list_by_replica(replica_id)
    return [svc.serialize(t) for t in tags]


@router.post("/replicas/{replica_id}/emotion-tags/detect", response_model=List[Dict[str, Any]], status_code=status.HTTP_201_CREATED)
@router.post("/api/v1/replicas/{replica_id}/emotion-tags/detect", response_model=List[Dict[str, Any]], status_code=status.HTTP_201_CREATED)
def detect_replica_emotion_tags(
    replica_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    replica = db.query(Replica).filter(Replica.id == replica_id).first()
    if not replica:
        raise HTTPException(status_code=404, detail="Réplique non trouvée")
    svc = EmotionService(db)
    tags = svc.analyze_replica(replica)
    return [svc.serialize(t) for t in tags]


@router.get("/media/{media_id}/emotion-tags", response_model=List[Dict[str, Any]])
@router.get("/api/v1/media/{media_id}/emotion-tags", response_model=List[Dict[str, Any]])
def get_media_emotion_tags(
    media_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    media = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Média introuvable")
    svc = EmotionService(db)
    tags = svc.list_by_media(media_id)
    return [svc.serialize(t) for t in tags]


@router.post("/media/{media_id}/emotion-tags/detect", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
@router.post("/api/v1/media/{media_id}/emotion-tags/detect", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
def detect_media_emotion_tags(
    media_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    media = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Média introuvable")
    svc = EmotionService(db)
    result = svc.analyze_media_replicas(media_id)
    return result


@router.get("/projects/{project_id}/emotion-tags", response_model=List[Dict[str, Any]])
@router.get("/api/v1/projects/{project_id}/emotion-tags", response_model=List[Dict[str, Any]])
def get_project_emotion_tags(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    svc = EmotionService(db)
    tags = svc.list_by_project(project_id)
    return [svc.serialize(t) for t in tags]


@router.post("/projects/{project_id}/emotion-tags/detect", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
@router.post("/api/v1/projects/{project_id}/emotion-tags/detect", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
def detect_project_emotion_tags(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    svc = EmotionService(db)
    result = svc.analyze_project(project_id)
    return result


# Endpoint enrichi pour lister les répliques avec leurs EmotionTags (pour l'éditeur)
@router.get("/projects/{project_id}/replicas/with-emotions", response_model=List[Dict[str, Any]])
@router.get("/api/v1/projects/{project_id}/replicas/with-emotions", response_model=List[Dict[str, Any]])
def get_replicas_with_emotions(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_current_user_payload),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    media_ids = [m.id for m in db.query(MediaAsset).filter(MediaAsset.project_id == project_id).all()]
    if not media_ids:
        return []
    replicas = db.query(Replica).filter(Replica.media_id.in_(media_ids)).order_by(Replica.order_index, Replica.start_ms).all()
    svc = EmotionService(db)
    result = []
    for r in replicas:
        tags = svc.list_by_replica(r.id)
        # Construction réplique + tags pour front indicatif
        result.append({
            "id": str(r.id),
            "media_id": str(r.media_id),
            "speaker_id": str(r.speaker_id) if r.speaker_id else None,
            "text": r.text,
            "start_ms": r.start_ms,
            "end_ms": r.end_ms,
            "order_index": r.order_index,
            "typo_codes": r.typo_codes or {},
            "confidence_score": float(r.confidence_score) if r.confidence_score is not None else None,
            "is_manually_edited": r.is_manually_edited,
            "breath_marker": r.breath_marker,
            "emotion_tags": [svc.serialize(t) for t in tags],
            # Suggested codes agrégés (union des suggestions des tags)
            "suggested_typo_codes": _merge_suggestions(tags),
        })
    return result


def _merge_suggestions(tags: List[EmotionTag]) -> Dict[str, bool]:
    merged: Dict[str, bool] = {}
    for t in tags:
        if t.suggested_typo_codes:
            for k, v in t.suggested_typo_codes.items():
                if v:
                    merged[k] = True
    return merged
