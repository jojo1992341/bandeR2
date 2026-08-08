"""
Dashboard API §14.2.1 — Vue synthétique des projets d'un studio.

Endpoints :
  - GET /studios/{studio_id}/dashboard — Vue synthétique (projets + indicateurs)
  - GET /studios/{studio_id}/projects — Liste projets avec filtres par statut

Indicateurs studio :
  - Temps moyen de traitement (pipeline)
  - Volume traité dans le mois
  - Quota restant (minutes IA)
  - Répartition par statut
"""

import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_
from typing import Optional, List
from app.core.database import get_db
from app.models import Studio, Project, PipelineJob, MediaAsset
from app.domain.rules.project_lifecycle import ProjectStatus, _resolve_status

router = APIRouter()


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
    }


# ── GET dashboard ─────────────────────────────────────────────

@router.get("/studios/{studio_id}/dashboard", response_model=dict)
def get_studio_dashboard(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    §14.2.1 — Vue synthétique du dashboard pour un studio.

    Retourne :
      - projects : liste des projets du studio (avec statut, pipeline, dernière modif)
      - indicators : indicateurs studio (temps moyen, volume, quota, répartition statuts)
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
                # PipelineJob doesn't have created_at — estimate from project creation
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
    # Calculer l'usage réel si disponible (sinon estimer via les jobs)
    if not quotas.get("ai_minutes_used"):
        # Estimation : chaque job completed ≈ durée média du projet
        # Pour l'instant on utilise la valeur stockée ou 0
        total_used = 0
        for j in completed_jobs:
            proj = next((p for p in projects if p.id == j.project_id), None)
            if proj:
                # Estimer la durée média (via media asset)
                media = db.query(MediaAsset).filter(MediaAsset.project_id == proj.id).first()
                if media:
                    # On ne connaît pas la durée ici, on estime 20 min par projet
                    total_used += 20
        quota_used_minutes = total_used

    quota_remaining_minutes = max(0, quota_limit_minutes - quota_used_minutes)
    quota_percent_used = round((quota_used_minutes / quota_limit_minutes) * 100, 1) if quota_limit_minutes > 0 else 0

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
