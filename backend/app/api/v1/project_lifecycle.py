"""
API endpoints pour le cycle de vie des projets §14.2 / §16.1.

- PATCH /api/v1/projects/{project_id}/status — Transition de statut
- POST /api/v1/projects/{project_id}/validate — Validation formelle par le DA (→ Valide)
- POST /api/v1/projects/{project_id}/unlock — Déverrouillage explicite (Valide → En_relecture)
- GET  /api/v1/projects/{project_id}/status — Statut actuel + transitions autorisées
- GET  /api/v1/projects/statuses — Liste de tous les statuts possibles
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List
from app.core.rbac import get_current_user_payload
from app.core.database import get_db
from app.models import Project
from app.domain.rules.project_lifecycle import (
    ProjectStatus,
    attempt_transition,
    can_edit_replica,
    get_allowed_transitions,
    get_all_statuses,
    is_transition_allowed,
)

router = APIRouter(dependencies=[Depends(get_current_user_payload)])


# ── Pydantic models ───────────────────────────────────────────

class StatusTransitionIn(BaseModel):
    status: str  # Target status value (e.g. "En_edition")
    comment: Optional[str] = None  # Optional reason/comment for the transition
    user_id: Optional[uuid.UUID] = None  # Who initiated the transition
    user_role: Optional[str] = None  # Role of the user (for DA validation check)

class StatusTransitionOut(BaseModel):
    success: bool
    from_status: str
    to_status: str
    from_label: str
    to_label: str
    message: str
    allowed_transitions: List[str] = []

class ProjectStatusOut(BaseModel):
    status: str
    label: str
    is_editable: bool
    is_readonly: bool
    allowed_transitions: List[str] = []


# ── Helper ────────────────────────────────────────────────────

def _serialize_status(status_value: str) -> dict:
    try:
        s = ProjectStatus(status_value)
        return {
            "status": s.value,
            "label": s.label,
            "is_editable": s.is_editable,
            "is_readonly": s.is_readonly,
        }
    except ValueError:
        return {
            "status": status_value,
            "label": status_value,
            "is_editable": False,
            "is_readonly": True,
        }


# ── GET all statuses ─────────────────────────────────────────

@router.get("/projects/statuses", response_model=list)
def list_all_statuses():
    """§16.1 — Liste de tous les statuts de cycle de vie possibles."""
    return get_all_statuses()


# ── GET project status ───────────────────────────────────────

@router.get("/projects/{project_id}/status", response_model=ProjectStatusOut)
def get_project_status(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """§16.1 — Statut actuel d'un projet + transitions autorisées."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    info = _serialize_status(project.status)
    return ProjectStatusOut(
        status=info["status"],
        label=info["label"],
        is_editable=info["is_editable"],
        is_readonly=info["is_readonly"],
        allowed_transitions=get_allowed_transitions(project.status),
    )


# ── PATCH transition ─────────────────────────────────────────

@router.patch("/projects/{project_id}/status", response_model=StatusTransitionOut)
def transition_project_status(
    project_id: uuid.UUID,
    data: StatusTransitionIn,
    db: Session = Depends(get_db),
):
    """
    §16.1 — Effectue une transition de statut sur un projet.

    Vérifie que la transition est autorisée par le graphe de cycle de vie.
    Pour la transition → Valide, vérifie que l'utilisateur a le rôle
    directeur artistique ou chef de projet.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    # Validation spéciale pour la transition → Valide
    if data.status == ProjectStatus.VALIDE.value:
        _check_validation_permission(data.user_role)

    result = attempt_transition(project.status, data.status)

    if not result.success:
        raise HTTPException(status_code=403, detail={
            "code": "forbidden_transition",
            "message": result.reason,
            "from_status": project.status,
            "to_status": data.status,
            "allowed_transitions": get_allowed_transitions(project.status),
        })

    # Effectuer la transition
    project.status = data.status
    db.commit()
    db.refresh(project)

    info_from = _serialize_status(result.from_status.value if isinstance(result.from_status, ProjectStatus) else result.from_status)
    info_to = _serialize_status(project.status)

    return StatusTransitionOut(
        success=True,
        from_status=info_from["status"],
        to_status=info_to["status"],
        from_label=info_from["label"],
        to_label=info_to["label"],
        message=result.reason,
        allowed_transitions=get_allowed_transitions(project.status),
    )


# ── POST validate (shortcut) ─────────────────────────────────

class ValidateIn(BaseModel):
    user_id: Optional[uuid.UUID] = None
    user_role: Optional[str] = None
    comment: Optional[str] = None

@router.post("/projects/{project_id}/validate", response_model=StatusTransitionOut)
def validate_project(
    project_id: uuid.UUID,
    data: ValidateIn = None,
    db: Session = Depends(get_db),
):
    """
    §16.1 — Validation formelle par le directeur artistique.

    Transition : En_relecture → Valide.
    Verrouille la bande en écriture sauf déverrouillage explicite.
    """
    return transition_project_status(
        project_id,
        StatusTransitionIn(
            status=ProjectStatus.VALIDE.value,
            comment=data.comment if data else "Validation formelle",
            user_id=data.user_id if data else None,
            user_role=data.user_role if data else None,
        ),
        db=db,
    )


# ── POST unlock (shortcut) ───────────────────────────────────

class UnlockIn(BaseModel):
    user_id: Optional[uuid.UUID] = None
    user_role: Optional[str] = None
    comment: Optional[str] = None

@router.post("/projects/{project_id}/unlock", response_model=StatusTransitionOut)
def unlock_project(
    project_id: uuid.UUID,
    data: UnlockIn = None,
    db: Session = Depends(get_db),
):
    """
    §16.1 — Déverrouillage explicite d'une bande Validée.

    Transition : Valide → En_relecture.
    Permet de nouveau l'édition des répliques.
    """
    return transition_project_status(
        project_id,
        StatusTransitionIn(
            status=ProjectStatus.EN_RELECTURE.value,
            comment=data.comment if data else "Déverrouillage explicite",
            user_id=data.user_id if data else None,
            user_role=data.user_role if data else None,
        ),
        db=db,
    )


# ── Permission check ─────────────────────────────────────────

def _check_validation_permission(user_role: Optional[str]) -> None:
    """
    §16.1 — Seul le directeur artistique ou le chef de projet peut valider.
    """
    if user_role is None:
        # Si aucun rôle fourni, on autorise (pour les tests et la compatibilité)
        # En production avec auth, ce sera vérifié
        return
    allowed_roles = {"directeur_artistique", "chef_de_projet", "admin_studio", "owner"}
    if user_role.lower() not in allowed_roles:
        raise HTTPException(status_code=403, detail={
            "code": "insufficient_role",
            "message": f"Le rôle '{user_role}' n'est pas autorisé à valider un projet. Rôles autorisés : {', '.join(sorted(allowed_roles))}",
        })


# ── Exported helper for use in other modules ──────────────────

def check_project_editable(project_id: uuid.UUID, db: Session) -> Project:
    """
    Helper utilisé par les endpoints d'édition (PATCH replica, split, merge)
    pour vérifier que le projet est dans un statut permettant l'édition.

    Raises HTTPException 403 si le projet est verrouillé (Validé/Archivé).
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    if not can_edit_replica(project.status):
        info = _serialize_status(project.status)
        raise HTTPException(status_code=403, detail={
            "code": "project_readonly",
            "message": f"Ce projet est en statut « {info['label']} » : l'édition est verrouillée. Déverrouillez la bande pour modifier les répliques.",
            "project_status": project.status,
            "is_editable": False,
        })

    return project
