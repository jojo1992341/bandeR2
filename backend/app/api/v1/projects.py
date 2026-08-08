import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.rbac import get_current_user_payload
from app.models import Project, Studio, StudioMembership, User

router = APIRouter()


class ProjectCreateIn(BaseModel):
    title: str
    studio_id: uuid.UUID
    source_lang: str = "fr"
    target_lang: str = "fr"


class ProjectOut(BaseModel):
    id: str
    title: str
    studio_id: str
    source_lang: str
    target_lang: str
    status: str


def _check_user_studio_access(
    db: Session, user_id: uuid.UUID, studio_id: uuid.UUID
) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    membership = (
        db.query(StudioMembership)
        .filter(
            StudioMembership.studio_id == studio_id,
            StudioMembership.user_id == user_id,
        )
        .first()
    )
    if membership:
        return True
    any_membership = (
        db.query(StudioMembership)
        .filter(StudioMembership.user_id == user_id)
        .first()
    )
    if not any_membership and user and user.role in ("owner", "admin"):
        return True
    return False


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/statuses", response_model=list)
def get_statuses():
    return [
        {"value": "Cree", "label": "Créé", "description": "Projet créé"},
        {
            "value": "En_traitement",
            "label": "En traitement",
            "description": "IA en cours",
        },
        {
            "value": "Pret_pour_edition",
            "label": "Prêt pour édition",
            "description": "IA terminée",
        },
        {
            "value": "En_edition",
            "label": "En édition",
            "description": "Édition en cours",
        },
        {
            "value": "En_relecture",
            "label": "En relecture",
            "description": "Relecture DA",
        },
        {"value": "Valide", "label": "Validé", "description": "Projet validé"},
        {
            "value": "Exporte_Livre",
            "label": "Exporté/Livré",
            "description": "Export terminé",
        },
        {"value": "Archive", "label": "Archivé", "description": "Archivé"},
    ]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    data: ProjectCreateIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = uuid.UUID(payload.get("sub"))
    if not _check_user_studio_access(db, user_id, data.studio_id):
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions for this studio (§15.7 IDOR protection)",
        )

    studio = db.query(Studio).filter(Studio.id == data.studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio not found")

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
    return ProjectOut(
        id=str(project.id),
        title=project.title,
        studio_id=str(project.studio_id),
        source_lang=project.source_lang,
        target_lang=project.target_lang,
        status=project.status,
    )


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = uuid.UUID(payload.get("sub"))
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not _check_user_studio_access(db, user_id, project.studio_id):
        raise HTTPException(
            status_code=404,
            detail="Project not found (§15.7 IDOR protection)",
        )

    return ProjectOut(
        id=str(project.id),
        title=project.title,
        studio_id=str(project.studio_id),
        source_lang=project.source_lang,
        target_lang=project.target_lang,
        status=project.status,
    )
