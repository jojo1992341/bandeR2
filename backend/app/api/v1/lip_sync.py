import uuid
import os
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import get_settings
from app.core.rbac import get_optional_user_payload, get_current_user_payload
from app.models import MediaAsset, Project

router = APIRouter()

@router.get("/media/{media_id}/lip-sync")
@router.get("/api/v1/media/{media_id}/lip-sync", response_model=Dict[str, Any])
def get_lip_sync(media_id: uuid.UUID, db: Session = Depends(get_db), payload: Optional[dict] = Depends(get_optional_user_payload)):
    from app.services.lip_sync_service import LipSyncService
    media = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Média non trouvé")
    svc = LipSyncService(db)
    result = svc.get_result(media_id)
    if not result:
        # Retourner courbe vide
        return {
            "media_id": str(media_id),
            "fps": svc.fps,
            "frame_count": 0,
            "face_visible_ratio": 0.0,
            "close_up_ratio": 0.0,
            "curve": [],
            "feature_enabled": svc.is_enabled(),
            "status": "no_data",
        }
    return {
        "media_id": str(result.media_id),
        "fps": result.fps,
        "frame_count": result.frame_count,
        "face_visible_ratio": result.face_visible_ratio,
        "close_up_ratio": result.close_up_ratio,
        "curve": result.curve or [],
        "detector_version": result.detector_version,
        "feature_enabled": result.feature_enabled,
        "created_at": result.created_at.isoformat() if result.created_at else None,
        "status": "ok",
    }

@router.post("/media/{media_id}/lip-sync/detect")
@router.post("/api/v1/media/{media_id}/lip-sync/detect", response_model=Dict[str, Any])
def detect_lip_sync(media_id: uuid.UUID, db: Session = Depends(get_db), payload: Optional[dict] = Depends(get_current_user_payload)):
    media = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Média non trouvé")
    from app.services.lip_sync_service import LipSyncService
    svc = LipSyncService(db)
    # Vérifier feature flag
    if not svc.is_enabled():
        return {
            "media_id": str(media_id),
            "status": "skipped",
            "feature_enabled": False,
            "reason": "feature_flag_disabled (§19.3)",
        }
    # Déclencher détection
    # Utiliser le storage_path comme chemin vidéo
    video_path = media.storage_path or f"/tmp/{media_id}.mp4"
    result = svc.detect_and_persist(media_id, video_path)
    return result

@router.get("/projects/{project_id}/lip-sync")
@router.get("/api/v1/projects/{project_id}/lip-sync", response_model=Dict[str, Any])
def get_project_lip_sync(project_id: uuid.UUID, db: Session = Depends(get_db), payload: Optional[dict] = Depends(get_optional_user_payload)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    from app.models import MediaAsset
    from app.services.lip_sync_service import LipSyncService
    medias = db.query(MediaAsset).filter(MediaAsset.project_id == project_id).all()
    svc = LipSyncService(db)
    results = []
    for m in medias:
        res = svc.get_result(m.id)
        if res:
            results.append({
                "media_id": str(m.id),
                "frame_count": res.frame_count,
                "face_visible_ratio": res.face_visible_ratio,
                "close_up_ratio": res.close_up_ratio,
                "feature_enabled": res.feature_enabled,
            })
        else:
            results.append({"media_id": str(m.id), "frame_count": 0, "face_visible_ratio": 0.0, "status": "no_data"})
    return {
        "project_id": str(project_id),
        "media_count": len(medias),
        "results": results,
        "feature_enabled": svc.is_enabled(),
    }

@router.post("/projects/{project_id}/lip-sync/detect")
@router.post("/api/v1/projects/{project_id}/lip-sync/detect", response_model=Dict[str, Any])
def detect_project_lip_sync(project_id: uuid.UUID, db: Session = Depends(get_db), payload: Optional[dict] = Depends(get_current_user_payload)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    from app.models import MediaAsset
    from app.services.lip_sync_service import LipSyncService
    medias = db.query(MediaAsset).filter(MediaAsset.project_id == project_id).all()
    svc = LipSyncService(db)
    if not svc.is_enabled():
        return {"project_id": str(project_id), "status": "skipped", "feature_enabled": False, "reason": "feature_flag_disabled"}
    results = []
    for m in medias:
        res = svc.detect_and_persist(m.id, m.storage_path or f"/tmp/{m.id}.mp4")
        results.append(res)
    return {"project_id": str(project_id), "results": results, "feature_enabled": True}

@router.get("/features")
@router.get("/api/v1/features", response_model=Dict[str, Any])
def get_features(payload: Optional[dict] = Depends(get_optional_user_payload)):
    settings = get_settings()
    return {
        "features": {
            "lip_sync": {
                "enabled": settings.is_feature_enabled("lip_sync"),
                "flag": "FEATURE_LIP_SYNC",
                "description": "Synchronisation labiale FaceMesh §8.2.6 / §11.4 (progressive deployment §19.3)",
                "fps": settings.LIP_SYNC_FPS,
                "confidence_threshold": settings.LIP_SYNC_CONFIDENCE_THRESHOLD,
            }
        },
        "all_flags": {k: v for k, v in os.environ.items() if k.startswith("FEATURE_")},
    }

@router.post("/features/{feature}/toggle")
@router.post("/api/v1/features/{feature}/toggle", response_model=Dict[str, Any])
def toggle_feature(feature: str, enabled: Optional[bool] = None, db: Session = Depends(get_db), payload: dict = Depends(get_current_user_payload)):
    # Vérifier admin (simplifié : role owner/admin)
    from app.core.rbac import normalize_role
    from app.models import User, StudioMembership
    # Vérifier que l'utilisateur est admin global ou d'un studio
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        uid = uuid.UUID(user_id)
    except:
        raise HTTPException(status_code=401, detail="ID invalide")
    user = db.query(User).filter(User.id == uid).first()
    if not user or normalize_role(user.role) not in ("owner", "admin"):
        # Vérifier membership admin
        membership = db.query(StudioMembership).filter(StudioMembership.user_id == uid).first()
        if not membership or normalize_role(membership.role) not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Admin requis pour toggler feature flag")
    # Toggle via env var en mémoire (pour le process courant)
    # En production ce serait en base ou config service, ici on modifie os.environ et clear cache
    if enabled is None:
        # Toggle
        current = get_settings().is_feature_enabled(feature)
        enabled = not current
    os.environ["FEATURE_LIP_SYNC" if feature.lower() in ("lip_sync", "lipsync") else f"FEATURE_{feature.upper()}"] = "1" if enabled else "0"
    # Clear cache
    get_settings.cache_clear()
    new_settings = get_settings()
    return {
        "feature": feature,
        "enabled": new_settings.is_feature_enabled(feature) if feature.lower() not in ("lip_sync", "lipsync") else new_settings.FEATURE_LIP_SYNC_ENABLED,
        "status": "toggled",
    }
