"""
API Tâches & Vue « Mon activité » (§16.2 CDC)

« Vue "Mon activité" récapitulant les projets récents et les tâches assignées. »

- Tâches studio-scopées, isolées par tenant (§15.7 IDOR).
- L'assignataire (`assignee_id`) doit appartenir au même studio.
- `/users/me/activity` agrège les projets récents et les tâches assignées de
  l'utilisateur authentifié, sur l'ensemble de ses studios (jamais ceux d'autrui).
"""

from __future__ import annotations

import uuid
from datetime import datetime
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
)
from app.models import (
    Project,
    StudioMembership,
    Task,
)
from app.models.task import TASK_STATUSES, DEFAULT_TASK_STATUS

router = APIRouter()


# ------------------------------------------------------------------
# Schémas
# ------------------------------------------------------------------
class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    assignee_id: Optional[str] = None
    status: str = DEFAULT_TASK_STATUS
    due_date: Optional[datetime] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[str] = None
    assignee_id: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[datetime] = None


class TaskOut(BaseModel):
    id: str
    studio_id: str
    project_id: Optional[str]
    title: str
    description: Optional[str]
    status: str
    assignee_id: Optional[str]
    created_by: Optional[str]
    due_date: Optional[datetime]


def _serialize_task(t: Task) -> TaskOut:
    return TaskOut(
        id=str(t.id),
        studio_id=str(t.studio_id),
        project_id=str(t.project_id) if t.project_id else None,
        title=t.title,
        description=t.description,
        status=t.status,
        assignee_id=str(t.assignee_id) if t.assignee_id else None,
        created_by=str(t.created_by) if t.created_by else None,
        due_date=t.due_date,
    )


def _resolve_assignee(
    db: Session, studio_id: uuid.UUID, assignee_id: Optional[str]
) -> Optional[uuid.UUID]:
    """Valide que l'assignataire appartient au studio (anti-IDOR cross-tenant)."""
    if not assignee_id:
        return None
    target = uuid.UUID(assignee_id)
    is_member = (
        db.query(StudioMembership)
        .filter(
            StudioMembership.studio_id == studio_id,
            StudioMembership.user_id == target,
        )
        .first()
    )
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignataire introuvable dans ce studio (§15.7 IDOR protection)",
        )
    return target


# ------------------------------------------------------------------
# CRUD Tâches
# ------------------------------------------------------------------
@router.get("/studios/{studio_id}/tasks", response_model=List[TaskOut])
def list_tasks(
    studio_id: uuid.UUID,
    assignee_id: Optional[str] = None,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    q = db.query(Task).filter(Task.studio_id == studio_id)
    if assignee_id:
        q = q.filter(Task.assignee_id == uuid.UUID(assignee_id))
    q = q.order_by(Task.created_at.desc())
    return [_serialize_task(t) for t in q.all()]


@router.post(
    "/studios/{studio_id}/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    studio_id: uuid.UUID,
    data: TaskCreate,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)

    if data.status not in TASK_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Statut invalide (valeurs: {', '.join(TASK_STATUSES)})",
        )

    project_id = None
    if data.project_id:
        project = (
            db.query(Project)
            .filter(Project.id == uuid.UUID(data.project_id))
            .first()
        )
        if not project or project.studio_id != studio_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Projet introuvable dans ce studio (§15.7 IDOR protection)",
            )
        project_id = project.id

    assignee_id = _resolve_assignee(db, studio_id, data.assignee_id)

    task = Task(
        studio_id=studio_id,
        project_id=project_id,
        title=data.title,
        description=data.description,
        status=data.status,
        assignee_id=assignee_id,
        created_by=user_id,
        due_date=data.due_date,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _serialize_task(task)


@router.get("/studios/{studio_id}/tasks/{task_id}", response_model=TaskOut)
def get_task(
    studio_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    task = (
        db.query(Task)
        .filter(Task.id == task_id, Task.studio_id == studio_id)
        .first()
    )
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tâche introuvable (§15.7 IDOR protection)",
        )
    return _serialize_task(task)


@router.put("/studios/{studio_id}/tasks/{task_id}", response_model=TaskOut)
def update_task(
    studio_id: uuid.UUID,
    task_id: uuid.UUID,
    data: TaskUpdate,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    task = (
        db.query(Task)
        .filter(Task.id == task_id, Task.studio_id == studio_id)
        .first()
    )
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tâche introuvable (§15.7 IDOR protection)",
        )

    if data.title is not None:
        task.title = data.title
    if data.description is not None:
        task.description = data.description
    if data.status is not None:
        if data.status not in TASK_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Statut invalide (valeurs: {', '.join(TASK_STATUSES)})",
            )
        task.status = data.status
    if data.due_date is not None:
        task.due_date = data.due_date
    if data.project_id is not None:
        if data.project_id == "":
            task.project_id = None
        else:
            project = (
                db.query(Project)
                .filter(Project.id == uuid.UUID(data.project_id))
                .first()
            )
            if not project or project.studio_id != studio_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Projet introuvable dans ce studio (§15.7 IDOR protection)",
                )
            task.project_id = project.id
    if "assignee_id" in data.model_fields_set:
        if data.assignee_id is None or data.assignee_id == "":
            task.assignee_id = None
        else:
            task.assignee_id = _resolve_assignee(
                db, studio_id, data.assignee_id
            )

    db.commit()
    db.refresh(task)
    return _serialize_task(task)


@router.delete(
    "/studios/{studio_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_task(
    studio_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    task = (
        db.query(Task)
        .filter(Task.id == task_id, Task.studio_id == studio_id)
        .first()
    )
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tâche introuvable (§15.7 IDOR protection)",
        )
    db.delete(task)
    db.commit()
    return None


# ------------------------------------------------------------------
# Vue « Mon activité »
# ------------------------------------------------------------------
class ActivityProject(BaseModel):
    id: str
    studio_id: str
    title: str
    status: str
    updated_at: Optional[datetime]


class ActivityOut(BaseModel):
    recent_projects: List[ActivityProject]
    assigned_tasks: List[TaskOut]


@router.get("/users/me/activity", response_model=ActivityOut)
def my_activity(
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """
    Vue « Mon activité » : projets récents et tâches assignées de l'utilisateur,
    limités aux studios dont il est membre (anti-IDOR).
    """
    user_id = get_user_id_from_payload(payload)
    user_studios = get_user_studio_ids(db, user_id)

    recent_projects: List[ActivityProject] = []
    assigned_tasks: List[TaskOut] = []

    if user_studios:
        projs = (
            db.query(Project)
            .filter(Project.studio_id.in_(user_studios))
            .order_by(Project.updated_at.desc())
            .limit(20)
            .all()
        )
        recent_projects = [
            ActivityProject(
                id=str(p.id),
                studio_id=str(p.studio_id),
                title=p.title,
                status=p.status,
                updated_at=p.updated_at,
            )
            for p in projs
        ]

        tasks = (
            db.query(Task)
            .filter(
                Task.assignee_id == user_id,
                Task.studio_id.in_(user_studios),
            )
            .order_by(Task.created_at.desc())
            .limit(50)
            .all()
        )
        assigned_tasks = [_serialize_task(t) for t in tasks]

    return ActivityOut(
        recent_projects=recent_projects, assigned_tasks=assigned_tasks
    )
