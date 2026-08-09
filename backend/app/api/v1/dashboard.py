"""
Dashboard API §14.2.1 — Vue synthétique des projets d'un studio.
Enrichi §16.1 + US-053 approfondi (usage/performance par projet)

Endpoints :
  - GET /studios/{studio_id}/dashboard — Vue synthétique (projets + indicateurs)
  - GET /studios/{studio_id}/projects — Liste projets avec filtres par statut

Indicateurs studio :
  - Temps moyen de traitement (pipeline)
  - Volume traité dans le mois
  - Quota restant (minutes IA)
  - Répartition par statut
  - (Enrichi) Durée totale, répliques, speakers, confiance moyenne, stockage
"""

import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_
from typing import Optional, List
from app.core.rbac import get_current_user_payload
from app.core.database import get_db
from app.models import Studio, Project, PipelineJob, MediaAsset, Replica, Speaker, TranscriptSegment, Word
from app.domain.rules.project_lifecycle import ProjectStatus, _resolve_status

router = APIRouter(dependencies=[Depends(get_current_user_payload)])


# ── Helpers ───────────────────────────────────────────────────

def _status_label(status_value: str) -> str:
    try:
        return _resolve_status(status_value).label
    except ValueError:
        return status_value


def _status_is_editable(status_value: str) -> bool:
    try:
        return _resolve_status(status_value).is_editable
    except ValueError:
        return True


def _get_project_stats(project: Project, db: Session) -> dict:
    """Calcule les statistiques de performance/usage pour un projet (US-053 approfondi)."""
    # Media assets
    medias = db.query(MediaAsset).filter(MediaAsset.project_id == project.id).all()
    media_ids = [m.id for m in medias]
    # Répliques
    replicas = []
    speakers = []
    transcripts = []
    words = []
    if media_ids:
        replicas = db.query(Replica).filter(Replica.media_id.in_(media_ids)).all()
        transcripts = db.query(TranscriptSegment).filter(TranscriptSegment.media_id.in_(media_ids)).all()
        # Words via transcript segments
        if transcripts:
            seg_ids = [s.id for s in transcripts]
            words = db.query(Word).filter(Word.segment_id.in_(seg_ids)).all()
    # Speakers pour le projet
    speakers = db.query(Speaker).filter(Speaker.project_id == project.id).all()

    replica_count = len(replicas)
    speaker_count = len(speakers)
    transcript_count = len(transcripts)
    word_count = len(words)

    # Confiance moyenne
    avg_confidence = None
    if replicas:
        scores = [float(r.confidence_score) for r in replicas if r.confidence_score is not None]
        if scores:
            avg_confidence = round(sum(scores) / len(scores), 3)

    # Durée totale : max end_ms des répliques ou duration_seconds des medias
    total_duration_seconds = 0
    if medias:
        for m in medias:
            if m.duration_seconds and m.duration_seconds > 0:
                total_duration_seconds += float(m.duration_seconds)
            else:
                # Fallback : max end_ms
                max_end = max((r.end_ms for r in replicas), default=0)
                if max_end:
                    total_duration_seconds = max(total_duration_seconds, max_end / 1000.0)
    elif replicas:
        max_end = max((r.end_ms for r in replicas), default=0)
        total_duration_seconds = max_end / 1000.0

    # Stockage estimé : file_size_bytes des medias
    storage_bytes = sum(m.file_size_bytes for m in medias if m.file_size_bytes) if medias else 0
    storage_mb = round(storage_bytes / (1024*1024), 2) if storage_bytes else 0.0

    # Pipeline performance : temps de traitement pour ce projet
    job = db.query(PipelineJob).filter(PipelineJob.project_id == project.id).order_by(PipelineJob.updated_at.desc()).first()
    pipeline_duration = None
    pipeline_status = job.status if job else None
    if job and job.status == "completed" and job.updated_at and project.created_at:
        try:
            j_upd = job.updated_at.replace(tzinfo=timezone.utc) if job.updated_at.tzinfo is None else job.updated_at
            p_cr = project.created_at.replace(tzinfo=timezone.utc) if project.created_at.tzinfo is None else project.created_at
            delta = j_upd - p_cr
            if delta.total_seconds() > 0:
                pipeline_duration = round(delta.total_seconds(), 1)
        except:
            pass

    return {
        "replica_count": replica_count,
        "speaker_count": speaker_count,
        "transcript_segment_count": transcript_count,
        "word_count": word_count,
        "avg_confidence": avg_confidence,
        "total_duration_seconds": round(total_duration_seconds, 2) if total_duration_seconds else 0.0,
        "total_duration_minutes": round(total_duration_seconds / 60, 2) if total_duration_seconds else 0.0,
        "storage_bytes": storage_bytes,
        "storage_mb": storage_mb,
        "pipeline_duration_seconds": pipeline_duration,
        "pipeline_status": pipeline_status,
    }


def _serialize_project_row(p: Project, db: Session) -> dict:
    """Serialise un projet avec avancement pipeline et dernière modification."""
    # Dernier job pipeline
    job = (
        db.query(PipelineJob)
        .filter(PipelineJob.project_id == p.id)
        .order_by(PipelineJob.updated_at.desc())
        .first()
    )

    pipeline_info = None
    if job:
        pipeline_info = {
            "status": job.status,
            "progress_percent": job.progress_percent,
            "current_step": job.current_step,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }

    # Stats enrichies US-053
    stats = _get_project_stats(p, db)

    return {
        "id": str(p.id),
        "title": p.title,
        "source_lang": p.source_lang,
        "target_lang": p.target_lang,
        "status": p.status,
        "status_label": _status_label(p.status),
        "is_editable": _status_is_editable(p.status),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "pipeline": pipeline_info,
        "stats": stats,
        # Champs aplatis pour compatibilité / tri
        "replica_count": stats["replica_count"],
        "speaker_count": stats["speaker_count"],
        "avg_confidence": stats["avg_confidence"],
        "duration_seconds": stats["total_duration_seconds"],
    }


# ── GET dashboard ─────────────────────────────────────────────

@router.get("/studios/{studio_id}/dashboard", response_model=dict)
def get_studio_dashboard(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    §14.2.1 — Vue synthétique du dashboard pour un studio.
    Enrichi §16.1 + US-053 : statistiques d'usage/performance par projet

    Retourne :
      - projects : liste des projets du studio (avec statut, pipeline, dernière modif, stats)
      - indicators : indicateurs studio (temps moyen, volume, quota, répartition statuts, durée totale, etc.)
      - filters : statuts disponibles pour le filtrage
    """
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio non trouvé")

    # ── Projets ──
    projects = (
        db.query(Project)
        .filter(Project.studio_id == studio_id)
        .order_by(Project.updated_at.desc())
        .all()
    )
    project_list = [_serialize_project_row(p, db) for p in projects]

    # ── Indicateurs studio ──
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    # Répartition par statut
    status_counts_raw = (
        db.query(Project.status, func.count(Project.id))
        .filter(Project.studio_id == studio_id)
        .group_by(Project.status)
        .all()
    )
    status_counts = {status: count for status, count in status_counts_raw}
    status_distribution = []
    for status_value, count in status_counts_raw:
        status_distribution.append({
            "status": status_value,
            "label": _status_label(status_value),
            "count": count,
        })
    status_distribution.sort(key=lambda x: x["count"], reverse=True)

    # Volume traité dans le mois (projets passés en Pret_pour_edition ou au-delà)
    volume_month = (
        db.query(func.count(Project.id))
        .filter(
            Project.studio_id == studio_id,
            Project.updated_at >= thirty_days_ago,
            Project.status.in_([
                "Pret_pour_edition", "En_edition", "En_relecture",
                "Valide", "Exporte_Livre", "Archive",
            ]),
        )
        .scalar() or 0
    )

    # Temps moyen de traitement pipeline (basé sur les jobs terminés)
    completed_jobs = (
        db.query(PipelineJob)
        .filter(
            PipelineJob.project_id.in_([p.id for p in projects]),
            PipelineJob.status == "completed",
        )
        .all()
    )
    avg_processing_seconds = None
    if completed_jobs:
        durations = []
        for j in completed_jobs:
            if j.updated_at:
                proj = next((p for p in projects if p.id == j.project_id), None)
                if proj and proj.created_at:
                    try:
                        j_updated = j.updated_at.replace(tzinfo=timezone.utc) if j.updated_at.tzinfo is None else j.updated_at
                        p_created = proj.created_at.replace(tzinfo=timezone.utc) if proj.created_at.tzinfo is None else proj.created_at
                        delta = j_updated - p_created
                        if delta.total_seconds() > 0:
                            durations.append(delta.total_seconds())
                    except Exception:
                        pass
        if durations:
            avg_processing_seconds = round(sum(durations) / len(durations), 1)

    # Quota restant (minutes IA)
    quotas = studio.quotas or {}
    quota_limit_minutes = quotas.get("ai_minutes_limit", 600)  # défaut 10h/mois
    quota_used_minutes = quotas.get("ai_minutes_used", 0)
    if not quotas.get("ai_minutes_used"):
        total_used = 0
        for j in completed_jobs:
            proj = next((p for p in projects if p.id == j.project_id), None)
            if proj:
                media = db.query(MediaAsset).filter(MediaAsset.project_id == proj.id).first()
                if media:
                    total_used += 20
        quota_used_minutes = total_used

    quota_remaining_minutes = max(0, quota_limit_minutes - quota_used_minutes)
    quota_percent_used = round((quota_used_minutes / quota_limit_minutes) * 100, 1) if quota_limit_minutes > 0 else 0

    # ── Indicateurs enrichis US-053 ──
    # Totaux
    total_replicas = sum(p["stats"]["replica_count"] for p in project_list) if project_list else 0
    total_speakers = sum(p["stats"]["speaker_count"] for p in project_list) if project_list else 0
    total_duration_seconds = sum(p["stats"]["total_duration_seconds"] for p in project_list) if project_list else 0
    total_storage_mb = sum(p["stats"]["storage_mb"] for p in project_list) if project_list else 0
    total_words = sum(p["stats"]["word_count"] for p in project_list) if project_list else 0
    total_transcripts = sum(p["stats"]["transcript_segment_count"] for p in project_list) if project_list else 0

    # Confiance moyenne globale
    all_confidences = []
    for p in projects:
        medias = db.query(MediaAsset).filter(MediaAsset.project_id == p.id).all()
        mids = [m.id for m in medias]
        if mids:
            reps = db.query(Replica).filter(Replica.media_id.in_(mids)).all()
            for r in reps:
                if r.confidence_score is not None:
                    all_confidences.append(float(r.confidence_score))
    avg_confidence_global = round(sum(all_confidences) / len(all_confidences), 3) if all_confidences else None

    # Top projets par activité (dernière mise à jour)
    top_projects = sorted(project_list, key=lambda x: x.get("updated_at") or "", reverse=True)[:5]

    indicators = {
        "total_projects": len(projects),
        "status_distribution": status_distribution,
        "volume_month": volume_month,
        "avg_processing_seconds": avg_processing_seconds,
        "quota": {
            "limit_minutes": quota_limit_minutes,
            "used_minutes": quota_used_minutes,
            "remaining_minutes": quota_remaining_minutes,
            "percent_used": quota_percent_used,
        },
        # Enrichis US-053
        "total_replicas": total_replicas,
        "total_speakers": total_speakers,
        "total_duration_seconds": round(total_duration_seconds, 2),
        "total_duration_minutes": round(total_duration_seconds / 60, 2) if total_duration_seconds else 0.0,
        "total_duration_hours": round(total_duration_seconds / 3600, 2) if total_duration_seconds else 0.0,
        "total_storage_mb": round(total_storage_mb, 2),
        "total_words": total_words,
        "total_transcripts": total_transcripts,
        "avg_confidence_global": avg_confidence_global,
        "top_projects": [{"id": p["id"], "title": p["title"], "updated_at": p["updated_at"], "status": p["status"]} for p in top_projects],
    }

    # ── Filtres disponibles ──
    available_filters = [
        {"value": s.value, "label": s.label}
        for s in ProjectStatus
    ]

    return {
        "studio_id": str(studio_id),
        "studio_name": studio.name,
        "studio_plan": studio.plan,
        "projects": project_list,
        "indicators": indicators,
        "filters": available_filters,
    }


# ── GET projets filtrés ──────────────────────────────────────

@router.get("/studios/{studio_id}/projects", response_model=dict)
def list_studio_projects(
    studio_id: uuid.UUID,
    status: Optional[str] = Query(None, description="Filtrer par statut (ex: Valide, En_edition)"),
    statuses: Optional[str] = Query(None, description="Filtrer par plusieurs statuts (séparés par virgule)"),
    sort_by: Optional[str] = Query("updated_at", description="Tri: updated_at, title, status, created_at"),
    sort_order: Optional[str] = Query("desc", description="Ordre: asc, desc"),
    page: int = Query(1, ge=1, description="Page (1-indexed)"),
    per_page: int = Query(50, ge=1, le=200, description="Résultats par page"),
    db: Session = Depends(get_db),
):
    """
    §14.2.1 — Liste les projets d'un studio avec filtres par statut.
    """
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio non trouvé")

    query = db.query(Project).filter(Project.studio_id == studio_id)

    # Filtre par statut unique
    if status:
        query = query.filter(Project.status == status)

    # Filtre par plusieurs statuts
    if statuses:
        status_list = [s.strip() for s in statuses.split(",") if s.strip()]
        if status_list:
            query = query.filter(Project.status.in_(status_list))

    # Tri
    sort_column = Project.updated_at
    if sort_by == "title":
        sort_column = Project.title
    elif sort_by == "status":
        sort_column = Project.status
    elif sort_by == "created_at":
        sort_column = Project.created_at

    if sort_order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    # Pagination
    total = query.count()
    offset = (page - 1) * per_page
    projects = query.offset(offset).limit(per_page).all()

    return {
        "studio_id": str(studio_id),
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "projects": [_serialize_project_row(p, db) for p in projects],
    }
