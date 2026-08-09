"""
API Organisation des projets (§16.1 CDC)

« Système de tags et de dossiers pour organiser les projets par client, saison,
diffuseur. »

Toutes les ressources sont studio-scopées et isolées par tenant (§15.7 IDOR) :
- list/create vérifient l'appartenance au studio du chemin (403 sinon) ;
- accès par identifiant vérifient que la ressource appartient bien à un studio
  de l'utilisateur (404 sinon — pas de fuite d'existence).
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import get_current_user_payload
from app.core.tenant import (
    get_user_id_from_payload,
    get_user_studio_ids,
    require_membership,
    require_resource_in_user_studio,
)
from app.models import Project, ProjectFolder, ProjectTag

router = APIRouter(dependencies=[Depends(get_current_user_payload)])


# ------------------------------------------------------------------
# Schémas
# ------------------------------------------------------------------
class FolderCreate(BaseModel):
    name: str
    parent_folder_id: Optional[str] = None


class FolderUpdate(BaseModel):
    name: Optional[str] = None
    parent_folder_id: Optional[str] = None


class FolderOut(BaseModel):
    id: str
    studio_id: str
    name: str
    parent_folder_id: Optional[str]


class TagCreate(BaseModel):
    name: str
    color: str = "#6366f1"


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class TagOut(BaseModel):
    id: str
    studio_id: str
    name: str
    color: str


class ProjectOrganize(BaseModel):
    folder_id: Optional[str] = None
    tag_ids: Optional[List[str]] = None


def _serialize_folder(f: ProjectFolder) -> FolderOut:
    return FolderOut(
        id=str(f.id),
        studio_id=str(f.studio_id),
        name=f.name,
        parent_folder_id=str(f.parent_folder_id) if f.parent_folder_id else None,
    )


def _serialize_tag(t: ProjectTag) -> TagOut:
    return TagOut(
        id=str(t.id), studio_id=str(t.studio_id), name=t.name, color=t.color
    )


# ------------------------------------------------------------------
# Dossiers
# ------------------------------------------------------------------
@router.get("/studios/{studio_id}/folders", response_model=List[FolderOut])
def list_folders(
    studio_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    folders = (
        db.query(ProjectFolder)
        .filter(ProjectFolder.studio_id == studio_id)
        .order_by(ProjectFolder.name)
        .all()
    )
    return [_serialize_folder(f) for f in folders]


@router.post(
    "/studios/{studio_id}/folders",
    response_model=FolderOut,
    status_code=status.HTTP_201_CREATED,
)
def create_folder(
    studio_id: uuid.UUID,
    data: FolderCreate,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)

    parent_id = None
    if data.parent_folder_id:
        parent = (
            db.query(ProjectFolder)
            .filter(ProjectFolder.id == uuid.UUID(data.parent_folder_id))
            .first()
        )
        if not parent or parent.studio_id != studio_id:
            # Anti-IDOR : le dossier parent doit appartenir au même studio
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dossier parent introuvable (§15.7 IDOR protection)",
            )
        parent_id = parent.id

    folder = ProjectFolder(
        studio_id=studio_id, name=data.name, parent_folder_id=parent_id
    )
    db.add(folder)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un dossier avec ce nom existe déjà dans ce studio",
        )
    db.refresh(folder)
    return _serialize_folder(folder)


@router.get("/studios/{studio_id}/folders/{folder_id}", response_model=FolderOut)
def get_folder(
    studio_id: uuid.UUID,
    folder_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    folder = (
        db.query(ProjectFolder)
        .filter(
            ProjectFolder.id == folder_id, ProjectFolder.studio_id == studio_id
        )
        .first()
    )
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier introuvable (§15.7 IDOR protection)",
        )
    return _serialize_folder(folder)


@router.put("/studios/{studio_id}/folders/{folder_id}", response_model=FolderOut)
def update_folder(
    studio_id: uuid.UUID,
    folder_id: uuid.UUID,
    data: FolderUpdate,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    folder = (
        db.query(ProjectFolder)
        .filter(
            ProjectFolder.id == folder_id, ProjectFolder.studio_id == studio_id
        )
        .first()
    )
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier introuvable (§15.7 IDOR protection)",
        )
    if data.name is not None:
        folder.name = data.name
    if data.parent_folder_id is not None:
        if data.parent_folder_id == "":
            folder.parent_folder_id = None
        else:
            parent = (
                db.query(ProjectFolder)
                .filter(ProjectFolder.id == uuid.UUID(data.parent_folder_id))
                .first()
            )
            if not parent or parent.studio_id != studio_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Dossier parent introuvable (§15.7 IDOR protection)",
                )
            if parent.id == folder.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Un dossier ne peut pas être son propre parent",
                )
            folder.parent_folder_id = parent.id
    db.commit()
    db.refresh(folder)
    return _serialize_folder(folder)


@router.delete("/studios/{studio_id}/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(
    studio_id: uuid.UUID,
    folder_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    folder = (
        db.query(ProjectFolder)
        .filter(
            ProjectFolder.id == folder_id, ProjectFolder.studio_id == studio_id
        )
        .first()
    )
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier introuvable (§15.7 IDOR protection)",
        )
    db.delete(folder)
    db.commit()
    return None


# ------------------------------------------------------------------
# Tags
# ------------------------------------------------------------------
@router.get("/studios/{studio_id}/tags", response_model=List[TagOut])
def list_tags(
    studio_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    tags = (
        db.query(ProjectTag)
        .filter(ProjectTag.studio_id == studio_id)
        .order_by(ProjectTag.name)
        .all()
    )
    return [_serialize_tag(t) for t in tags]


@router.post(
    "/studios/{studio_id}/tags",
    response_model=TagOut,
    status_code=status.HTTP_201_CREATED,
)
def create_tag(
    studio_id: uuid.UUID,
    data: TagCreate,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    tag = ProjectTag(studio_id=studio_id, name=data.name, color=data.color)
    db.add(tag)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un tag avec ce nom existe déjà dans ce studio",
        )
    db.refresh(tag)
    return _serialize_tag(tag)


@router.get("/studios/{studio_id}/tags/{tag_id}", response_model=TagOut)
def get_tag(
    studio_id: uuid.UUID,
    tag_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    tag = (
        db.query(ProjectTag)
        .filter(ProjectTag.id == tag_id, ProjectTag.studio_id == studio_id)
        .first()
    )
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag introuvable (§15.7 IDOR protection)",
        )
    return _serialize_tag(tag)


@router.put("/studios/{studio_id}/tags/{tag_id}", response_model=TagOut)
def update_tag(
    studio_id: uuid.UUID,
    tag_id: uuid.UUID,
    data: TagUpdate,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    tag = (
        db.query(ProjectTag)
        .filter(ProjectTag.id == tag_id, ProjectTag.studio_id == studio_id)
        .first()
    )
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag introuvable (§15.7 IDOR protection)",
        )
    if data.name is not None:
        tag.name = data.name
    if data.color is not None:
        tag.color = data.color
    db.commit()
    db.refresh(tag)
    return _serialize_tag(tag)


@router.delete("/studios/{studio_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    studio_id: uuid.UUID,
    tag_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    tag = (
        db.query(ProjectTag)
        .filter(ProjectTag.id == tag_id, ProjectTag.studio_id == studio_id)
        .first()
    )
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag introuvable (§15.7 IDOR protection)",
        )
    db.delete(tag)
    db.commit()
    return None


# ------------------------------------------------------------------
# Organisation d'un projet (affectation dossier + tags)
# ------------------------------------------------------------------
@router.post("/projects/{project_id}/organize")
def organize_project(
    project_id: uuid.UUID,
    data: ProjectOrganize,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projet introuvable (§15.7 IDOR protection)",
        )
    # Anti-IDOR : le projet doit appartenir à un studio de l'utilisateur
    user_studios = get_user_studio_ids(db, user_id)
    require_resource_in_user_studio(db, user_id, project.studio_id, user_studios)

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
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Dossier introuvable (§15.7 IDOR protection)",
                )
            project.folder_id = folder.id

    if data.tag_ids is not None:
        wanted = []
        for tid in data.tag_ids:
            tag = (
                db.query(ProjectTag)
                .filter(ProjectTag.id == uuid.UUID(tid))
                .first()
            )
            if not tag or tag.studio_id != project.studio_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tag {tid} introuvable (§15.7 IDOR protection)",
                )
            wanted.append(tag)
        project.tags = wanted

    db.commit()
    db.refresh(project)
    return {
        "project_id": str(project.id),
        "folder_id": str(project.folder_id) if project.folder_id else None,
        "tag_ids": [str(t.id) for t in project.tags],
    }
