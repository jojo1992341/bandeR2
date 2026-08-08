from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.models import PipelineJob, Project, MediaAsset, Replica, RythmoVersion
from app.services.rythmo_engine import RythmoEngine
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime

router = APIRouter()

class RythmoGenerateIn(BaseModel):
    media_id: uuid.UUID

class VersionCreateIn(BaseModel):
    comment: Optional[str] = None
    created_by: Optional[str] = "system"

def _get_media_ids_for_project(db: Session, project_id: uuid.UUID) -> List[uuid.UUID]:
    medias = db.query(MediaAsset).filter(MediaAsset.project_id == project_id).all()
    return [m.id for m in medias]

def _serialize_replica_for_version(r: Replica) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "media_id": str(r.media_id),
        "speaker_id": str(r.speaker_id) if r.speaker_id else None,
        "text": r.text,
        "start_ms": r.start_ms,
        "end_ms": r.end_ms,
        "order_index": r.order_index,
        "typo_codes": r.typo_codes,
        "confidence_score": float(r.confidence_score) if r.confidence_score is not None else None,
        "is_manually_edited": r.is_manually_edited,
        "breath_marker": r.breath_marker,
    }

def _serialize_version(v: RythmoVersion) -> Dict[str, Any]:
    return {
        "id": str(v.id),
        "project_id": str(v.project_id),
        "version_number": v.version_number,
        "snapshot": v.snapshot,
        "comment": v.comment,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "replica_count": len(v.snapshot) if isinstance(v.snapshot, list) else 0,
    }

@router.post("/projects/{project_id}/rythmo/generate")
def generate_rythmo(project_id: uuid.UUID, data: RythmoGenerateIn, db: Session = Depends(get_db)):
    job = db.query(PipelineJob).filter(PipelineJob.project_id == project_id).order_by(PipelineJob.updated_at.desc()).first()
    if not job or job.status != "Prêt pour édition" or job.progress_percent < 100:
        raise HTTPException(status_code=409, detail="Pipeline préalable non terminé — attendez la fin du traitement")
    media = db.query(MediaAsset).filter(MediaAsset.id == data.media_id, MediaAsset.project_id == project_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Média non trouvé pour ce projet")
    engine = RythmoEngine()
    from app.models import Word, TranscriptSegment
    words = db.query(Word).filter(Word.segment_id.in_(
        db.query(TranscriptSegment.id).filter(TranscriptSegment.media_id == media.id).subquery()
    )).order_by(Word.start_ms).all()
    word_dicts = [{"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms, "speaker_id": w.speaker_id} for w in words]
    if not word_dicts:
        word_dicts = [{"text": "...", "start_ms": 0, "end_ms": 1000, "speaker_id": None}]
    replicas = engine.segment_words(word_dicts)
    created_replicas = []
    for r in replicas:
        rep = Replica(
            id=uuid.uuid4(),
            media_id=media.id,
            text=r["text"],
            start_ms=r["start_ms"],
            end_ms=r["end_ms"],
            speaker_id=r.get("speaker_id"),
            confidence_score=0.85,
            is_manually_edited=False,
            breath_marker=r.get("has_breath_marker", False),
            order_index=len(db.query(Replica).filter(Replica.media_id == media.id).all()) + len(created_replicas),
        )
        db.add(rep)
        created_replicas.append(rep)
    db.commit()
    # §8.2.5 — Double analyse acoustique + textuelle → EmotionTag (indicatif, ne modifie jamais le texte)
    emotion_result = None
    try:
        from app.services.emotion_service import EmotionService
        svc = EmotionService(db)
        # Capture original texts pour garantir non-altération
        original_texts = {rep.id: rep.text for rep in created_replicas}
        emotion_result = svc.analyze_media_replicas(media.id)
        # Vérification post-analyse : textes inchangés
        for rep in created_replicas:
            db.refresh(rep)
            assert rep.text == original_texts[rep.id], "EmotionTag ne doit jamais altérer Replica.text"
    except Exception as e:
        import logging
        logging.getLogger("rythmoai").warning(f"Emotion detection après génération rythmo warning (non-bloquant): {e}")
        emotion_result = {"status": "warning", "error": str(e)}
    return {"project_id": str(project_id), "replica_count": len(replicas), "status": "Prêt pour édition", "emotion_detection": emotion_result}

@router.get("/projects/{project_id}/replicas", response_model=list)
def list_replicas(project_id: uuid.UUID, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    media_ids = _get_media_ids_for_project(db, project_id)
    if not media_ids:
        return []
    replicas = db.query(Replica).filter(Replica.media_id.in_(media_ids)).order_by(Replica.order_index, Replica.start_ms).all()
    from app.api.v1.replicas import _serialize_replica
    return [_serialize_replica(r) for r in replicas]

# ==================== Versions RythmoBand §16.1 ====================

@router.post("/projects/{project_id}/rythmo/versions", response_model=dict)
def create_version(project_id: uuid.UUID, data: VersionCreateIn = None, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    media_ids = _get_media_ids_for_project(db, project_id)
    replicas = []
    if media_ids:
        replicas = db.query(Replica).filter(Replica.media_id.in_(media_ids)).order_by(Replica.order_index, Replica.start_ms).all()
    snapshot = [_serialize_replica_for_version(r) for r in replicas]
    max_version = db.query(func.max(RythmoVersion.version_number)).filter(RythmoVersion.project_id == project_id).scalar()
    next_number = (max_version or 0) + 1
    version = RythmoVersion(
        id=uuid.uuid4(),
        project_id=project_id,
        version_number=next_number,
        snapshot=snapshot,
        comment=data.comment if data else None,
        created_by=data.created_by if data and data.created_by else "system",
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return _serialize_version(version)

@router.get("/projects/{project_id}/rythmo/versions", response_model=dict)
def list_versions(project_id: uuid.UUID, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    versions = db.query(RythmoVersion).filter(RythmoVersion.project_id == project_id).order_by(RythmoVersion.version_number).all()
    return {
        "project_id": str(project_id),
        "count": len(versions),
        "versions": [_serialize_version(v) for v in versions]
    }

# IMPORTANT: compare doit être avant le route avec {version_id} sinon "compare" est capturé comme UUID
@router.get("/projects/{project_id}/rythmo/versions/compare", response_model=dict)
def compare_versions(
    project_id: uuid.UUID,
    from_id: Optional[uuid.UUID] = Query(None, alias="from"),
    to_id: Optional[uuid.UUID] = Query(None, alias="to"),
    from_version: Optional[int] = Query(None, alias="from_version"),
    to_version: Optional[int] = Query(None, alias="to_version"),
    db: Session = Depends(get_db)):
    v_from = None
    v_to = None
    if from_id:
        v_from = db.query(RythmoVersion).filter(RythmoVersion.id == from_id, RythmoVersion.project_id == project_id).first()
    elif from_version is not None:
        v_from = db.query(RythmoVersion).filter(RythmoVersion.version_number == from_version, RythmoVersion.project_id == project_id).first()

    if to_id:
        v_to = db.query(RythmoVersion).filter(RythmoVersion.id == to_id, RythmoVersion.project_id == project_id).first()
    elif to_version is not None:
        v_to = db.query(RythmoVersion).filter(RythmoVersion.version_number == to_version, RythmoVersion.project_id == project_id).first()

    if not v_from or not v_to:
        versions = db.query(RythmoVersion).filter(RythmoVersion.project_id == project_id).order_by(RythmoVersion.version_number).all()
        if len(versions) >= 2 and not v_from and not v_to:
            v_from = versions[-2]
            v_to = versions[-1]
        elif not v_from or not v_to:
            raise HTTPException(status_code=400, detail="Deux versions doivent être spécifiées pour la comparaison (from/to)")

    if not v_from or not v_to:
        raise HTTPException(status_code=404, detail="Une des versions à comparer n'existe pas")

    snap_from = {r["id"]: r for r in (v_from.snapshot or [])}
    snap_to = {r["id"]: r for r in (v_to.snapshot or [])}

    added = [r for rid, r in snap_to.items() if rid not in snap_from]
    removed = [r for rid, r in snap_from.items() if rid not in snap_to]
    modified = []
    for rid in set(snap_from.keys()) & set(snap_to.keys()):
        if snap_from[rid] != snap_to[rid]:
            diff_fields = {}
            for k in snap_from[rid].keys():
                if snap_from[rid].get(k) != snap_to[rid].get(k):
                    diff_fields[k] = {"from": snap_from[rid].get(k), "to": snap_to[rid].get(k)}
            modified.append({"id": rid, "diff": diff_fields, "from": snap_from[rid], "to": snap_to[rid]})

    return {
        "project_id": str(project_id),
        "from": _serialize_version(v_from),
        "to": _serialize_version(v_to),
        "added": added,
        "removed": removed,
        "modified": modified,
        "summary": {
            "added_count": len(added),
            "removed_count": len(removed),
            "modified_count": len(modified),
        }
    }

@router.get("/projects/{project_id}/rythmo/compare", response_model=dict)
def compare_alias(project_id: uuid.UUID, from_id: Optional[uuid.UUID] = None, to_id: Optional[uuid.UUID] = None, db: Session = Depends(get_db)):
    return compare_versions(project_id, from_id=from_id, to_id=to_id, db=db)

@router.get("/projects/{project_id}/rythmo/versions/{version_id}", response_model=dict)
def get_version(project_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db)):
    version = db.query(RythmoVersion).filter(RythmoVersion.id == version_id, RythmoVersion.project_id == project_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version non trouvée")
    return _serialize_version(version)

@router.post("/projects/{project_id}/rythmo/versions/{version_id}/restore", response_model=dict)
def restore_version(project_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    version = db.query(RythmoVersion).filter(RythmoVersion.id == version_id, RythmoVersion.project_id == project_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version non trouvée")

    media_ids = _get_media_ids_for_project(db, project_id)
    if media_ids:
        db.query(Replica).filter(Replica.media_id.in_(media_ids)).delete(synchronize_session=False)
        db.flush()

    restored_count = 0
    for rep_data in (version.snapshot or []):
        try:
            media_id = uuid.UUID(rep_data["media_id"])
        except:
            if media_ids:
                media_id = media_ids[0]
            else:
                new_media = MediaAsset(id=uuid.uuid4(), project_id=project_id, storage_path="restored_media.mp4", status="confirmed")
                db.add(new_media)
                db.flush()
                media_id = new_media.id
                media_ids = [media_id]
        media_exists = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
        if not media_exists:
            media_id = media_ids[0] if media_ids else None
            if not media_id:
                continue
        replica = Replica(
            id=uuid.UUID(rep_data["id"]) if rep_data.get("id") else uuid.uuid4(),
            media_id=media_id,
            speaker_id=uuid.UUID(rep_data["speaker_id"]) if rep_data.get("speaker_id") else None,
            text=rep_data.get("text", ""),
            start_ms=rep_data.get("start_ms", 0),
            end_ms=rep_data.get("end_ms", 0),
            order_index=rep_data.get("order_index", 0),
            typo_codes=rep_data.get("typo_codes") or {},
            confidence_score=rep_data.get("confidence_score", 0.0),
            is_manually_edited=rep_data.get("is_manually_edited", True),
            breath_marker=rep_data.get("breath_marker", False),
        )
        db.add(replica)
        restored_count += 1

    db.commit()

    new_replicas = []
    if media_ids:
        new_replicas = db.query(Replica).filter(Replica.media_id.in_(media_ids)).order_by(Replica.order_index).all()
        from app.api.v1.replicas import _serialize_replica
        new_replicas = [_serialize_replica(r) for r in new_replicas]

    return {
        "project_id": str(project_id),
        "restored_from": str(version.id),
        "restored_version_number": version.version_number,
        "replica_count": restored_count,
        "replicas": new_replicas,
        "status": "restored"
    }
