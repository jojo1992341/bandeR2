"""
Ressource Projects (CDC §10.2 & §16.1) — G-013.

Endpoints :
- GET    /projects            → liste paginée (filtrée par studio du tenant)
- POST   /projects            → création
- GET    /projects/{id}       → consultation
- PATCH  /projects/{id}       → modification (métadonnées)
- DELETE /projects/{id}       → suppression contrôlée (owner/admin, cascade)
- GET    /projects/{id}/activity → journal d'activité du projet

Tous les endpoints appliquent :
- **RBAC** (authentification JWT) ;
- **isolation multi-tenant** : un utilisateur n'accède qu'aux projets de ses
  studios (anti-IDOR §15.7) ;
- **contexte RLS** PostgreSQL (`SET LOCAL app.current_studio_id`) pour les
  accès mono-projet (double barrière §9.6).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import get_current_user_payload, normalize_role
from app.core.rls_context import set_studio_context
from app.core.tenant import (
    get_user_id_from_payload,
    get_user_studio_ids,
    require_membership,
)
from app.models import (
    Comment,
    EmotionTag,
    Export,
    MediaAsset,
    PipelineJob,
    Project,
    ProjectFolder,
    RythmoBand,
    RythmoVersion,
    Speaker,
    StudioMembership,
    Task,
    User,
)
from app.models.replica import Replica

router = APIRouter(dependencies=[Depends(get_current_user_payload)])


# ------------------------------------------------------------------
# Schémas (contrat OpenAPI)
# ------------------------------------------------------------------
class ProjectCreateIn(BaseModel):
    title: str
    studio_id: uuid.UUID
    source_lang: str = "fr"
    target_lang: str = "fr"


class ProjectUpdateIn(BaseModel):
    title: Optional[str] = None
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    folder_id: Optional[str] = None


class ProjectOut(BaseModel):
    id: str
    title: str
    studio_id: str
    source_lang: Optional[str]
    target_lang: Optional[str]
    status: str
    folder_id: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class ProjectListResponse(BaseModel):
    items: List[ProjectOut]
    total: int
    page: int
    page_size: int


class ActivityEventOut(BaseModel):
    type: str
    timestamp: datetime
    summary: str
    entity_id: Optional[str]


class ActivityResponse(BaseModel):
    project_id: str
    events: List[ActivityEventOut]


# ------------------------------------------------------------------
# Helpers RBAC / tenant
# ------------------------------------------------------------------
def _serialize(p: Project) -> ProjectOut:
    return ProjectOut(
        id=str(p.id),
        title=p.title,
        studio_id=str(p.studio_id),
        source_lang=p.source_lang,
        target_lang=p.target_lang,
        status=p.status,
        folder_id=str(p.folder_id) if p.folder_id else None,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _load_project_for_user(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    """Charge un projet et vérifie l'appartenance à un studio de l'utilisateur."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    user_studios = get_user_studio_ids(db, user_id)
    if project.studio_id not in user_studios:
        # Anti-IDOR : on ne révèle pas l'existence du projet
        raise HTTPException(
            status_code=404,
            detail="Project not found (§15.7 IDOR protection)",
        )
    # Contexte RLS PostgreSQL (double barrière) — no-op sur SQLite.
    set_studio_context(db, project.studio_id)
    return project


def _is_studio_admin(db: Session, user_id: uuid.UUID, studio_id: uuid.UUID) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if user and normalize_role(user.role) in ("owner", "admin"):
        # admin global : doit quand même être membre du studio
        return (
            db.query(StudioMembership)
            .filter(
                StudioMembership.studio_id == studio_id,
                StudioMembership.user_id == user_id,
            )
            .first()
            is not None
        )
    m = (
        db.query(StudioMembership)
        .filter(
            StudioMembership.studio_id == studio_id,
            StudioMembership.user_id == user_id,
        )
        .first()
    )
    return bool(m and normalize_role(m.role) in ("owner", "admin"))


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------
@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/statuses", response_model=list)
def get_statuses(payload: dict = Depends(get_current_user_payload)):
    return [
        {"value": "Cree", "label": "Créé", "description": "Projet créé"},
        {"value": "En_traitement", "label": "En traitement", "description": "IA en cours"},
        {"value": "Pret_pour_edition", "label": "Prêt pour édition", "description": "IA terminée"},
        {"value": "En_edition", "label": "En édition", "description": "Édition en cours"},
        {"value": "En_relecture", "label": "En relecture", "description": "Relecture DA"},
        {"value": "Valide", "label": "Validé", "description": "Projet validé"},
        {"value": "Exporte_Livre", "label": "Exporté/Livré", "description": "Export terminé"},
        {"value": "Archive", "label": "Archivé", "description": "Archivé"},
    ]


@router.get("", response_model=ProjectListResponse)
@router.get("/", response_model=ProjectListResponse)
def list_projects(
    studio_id: Optional[uuid.UUID] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Liste paginée des projets des studios de l'utilisateur (anti-IDOR)."""
    user_id = get_user_id_from_payload(payload)
    user_studios = get_user_studio_ids(db, user_id)
    if not user_studios:
        return ProjectListResponse(items=[], total=0, page=page, page_size=page_size)

    if studio_id is not None:
        # Filtre explicite par studio : doit être membre (anti-IDOR)
        if studio_id not in user_studios:
            raise HTTPException(
                status_code=403,
                detail="Accès refusé à ce studio (§15.7 IDOR protection)",
            )
        scope = {studio_id}
    else:
        scope = user_studios

    q = db.query(Project).filter(Project.studio_id.in_(scope))
    if status_filter:
        q = q.filter(Project.status == status_filter)
    total = q.count()
    items = (
        q.order_by(Project.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ProjectListResponse(
        items=[_serialize(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    data: ProjectCreateIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, data.studio_id)
    set_studio_context(db, data.studio_id)

    project = Project(
        id=uuid.uuid4(),
        studio_id=data.studio_id,
        title=data.title,
        source_lang=data.source_lang,
        target_lang=data.target_lang,
        status="Cree",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _serialize(project)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    project = _load_project_for_user(db, user_id, project_id)
    return _serialize(project)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID,
    data: ProjectUpdateIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Modifie les métadonnées d'un projet (membre du studio)."""
    user_id = get_user_id_from_payload(payload)
    project = _load_project_for_user(db, user_id, project_id)

    if data.title is not None:
        project.title = data.title
    if data.source_lang is not None:
        project.source_lang = data.source_lang
    if data.target_lang is not None:
        project.target_lang = data.target_lang
    if data.folder_id is not None:
        if data.folder_id == "":
            project.folder_id = None
        else:
            folder = (
                db.query(ProjectFolder)
                .filter(ProjectFolder.id == uuid.UUID(data.folder_id))
                .first()
            )
            if not folder or folder.studio_id != project.studio_id:
                raise HTTPException(
                    status_code=404,
                    detail="Dossier introuvable dans ce studio (§15.7 IDOR protection)",
                )
            project.folder_id = folder.id

    db.commit()
    db.refresh(project)
    return _serialize(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Suppression contrôlée (owner/admin du studio) avec cascade des dépendances."""
    user_id = get_user_id_from_payload(payload)
    project = _load_project_for_user(db, user_id, project_id)
    if not _is_studio_admin(db, user_id, project.studio_id):
        raise HTTPException(
            status_code=403,
            detail="Suppression réservée aux administrateurs du studio",
        )
    _delete_project(db, project)
    return None


def _delete_project(db: Session, project: Project) -> None:
    """Suppression en cascade ordonnée (robuste SQLite + PostgreSQL)."""
    pid = project.id
    media_ids = [
        r[0]
        for r in db.query(MediaAsset.id)
        .filter(MediaAsset.project_id == pid)
        .all()
    ]
    band_ids = [
        r[0]
        for r in db.query(RythmoBand.id)
        .filter(RythmoBand.project_id == pid)
        .all()
    ]
    replica_ids = []
    if media_ids or band_ids:
        rq = db.query(Replica.id)
        if media_ids and band_ids:
            rq = rq.filter(
                (Replica.media_id.in_(media_ids))
                | (Replica.rythmo_band_id.in_(band_ids))
            )
        elif media_ids:
            rq = rq.filter(Replica.media_id.in_(media_ids))
        else:
            rq = rq.filter(Replica.rythmo_band_id.in_(band_ids))
        replica_ids = [r[0] for r in rq.all()]

    if replica_ids:
        db.query(Comment).filter(Comment.replica_id.in_(replica_ids)).delete(
            synchronize_session=False
        )
        db.query(Replica).filter(Replica.id.in_(replica_ids)).delete(
            synchronize_session=False
        )
    for model in (
        Export,
        PipelineJob,
        RythmoVersion,
        Task,
        Speaker,
        EmotionTag,
        RythmoBand,
        MediaAsset,
    ):
        db.query(model).filter(model.project_id == pid).delete(
            synchronize_session=False
        )
    db.delete(project)
    db.commit()


@router.get("/{project_id}/activity", response_model=ActivityResponse)
def project_activity(
    project_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Journal d'activité du projet (anti-IDOR : membre du studio)."""
    user_id = get_user_id_from_payload(payload)
    project = _load_project_for_user(db, user_id, project_id)
    pid = project.id

    events: List[ActivityEventOut] = []

    for m in (
        db.query(MediaAsset)
        .filter(MediaAsset.project_id == pid)
        .order_by(MediaAsset.created_at.desc())
        .limit(20)
        .all()
    ):
        events.append(
            ActivityEventOut(
                type="media_uploaded",
                timestamp=m.created_at,
                summary=f"Média importé : {m.storage_path}",
                entity_id=str(m.id),
            )
        )

    for v in (
        db.query(RythmoVersion)
        .filter(RythmoVersion.project_id == pid)
        .order_by(RythmoVersion.created_at.desc())
        .limit(20)
        .all()
    ):
        events.append(
            ActivityEventOut(
                type="version_saved",
                timestamp=v.created_at,
                summary=f"Version de bande enregistrée (v{v.version_number})",
                entity_id=str(v.id),
            )
        )

    for e in (
        db.query(Export)
        .filter(Export.project_id == pid)
        .order_by(Export.created_at.desc())
        .limit(20)
        .all()
    ):
        events.append(
            ActivityEventOut(
                type="export",
                timestamp=e.created_at,
                summary=f"Export {e.format} ({e.status})",
                entity_id=str(e.id),
            )
        )

    for t in (
        db.query(Task)
        .filter(Task.project_id == pid)
        .order_by(Task.created_at.desc())
        .limit(20)
        .all()
    ):
        events.append(
            ActivityEventOut(
                type="task",
                timestamp=t.created_at,
                summary=f"Tâche : {t.title} ({t.status})",
                entity_id=str(t.id),
            )
        )

    events.sort(key=lambda ev: ev.timestamp, reverse=True)
    events = events[:50]

    return ActivityResponse(project_id=str(pid), events=events)
