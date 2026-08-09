"""
API Équipes / sous-groupes (§16.3 CDC)

« Gestion des sous-groupes/équipes au sein d'un grand studio (ex. « Pôle
jeunesse », « Pôle films ») avec droits d'accès dédiés — fonctionnalité plan
Enterprise. »

Isolation stricte par studio (tenant) : aucune équipe d'un studio B n'est
visible ou modifiable par un membre du studio A (§15.7 IDOR protection).
La création d'équipes est réservée aux studios au plan Enterprise.
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
from app.models import Studio, StudioMembership, Team, TeamMembership, User

router = APIRouter()

ENTERPRISE_PLANS = {"enterprise"}


class TeamCreate(BaseModel):
    name: str
    description: Optional[str] = None


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class TeamOut(BaseModel):
    id: str
    studio_id: str
    name: str
    description: Optional[str]


class TeamMemberAdd(BaseModel):
    user_id: str
    role: str = "member"


class TeamMemberOut(BaseModel):
    id: str
    team_id: str
    user_id: str
    email: Optional[str]
    role: str


def _serialize_team(t: Team) -> TeamOut:
    return TeamOut(
        id=str(t.id),
        studio_id=str(t.studio_id),
        name=t.name,
        description=t.description,
    )


def _require_enterprise(db: Session, studio_id: uuid.UUID) -> None:
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Studio introuvable"
        )
    if (studio.plan or "free").lower() not in ENTERPRISE_PLANS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Les équipes sont réservées au plan Enterprise (§16.3)",
        )


@router.get("/studios/{studio_id}/teams", response_model=List[TeamOut])
def list_teams(
    studio_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    teams = (
        db.query(Team)
        .filter(Team.studio_id == studio_id)
        .order_by(Team.name)
        .all()
    )
    return [_serialize_team(t) for t in teams]


@router.post(
    "/studios/{studio_id}/teams",
    response_model=TeamOut,
    status_code=status.HTTP_201_CREATED,
)
def create_team(
    studio_id: uuid.UUID,
    data: TeamCreate,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    _require_enterprise(db, studio_id)

    team = Team(
        studio_id=studio_id, name=data.name, description=data.description
    )
    db.add(team)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Une équipe avec ce nom existe déjà dans ce studio",
        )
    db.refresh(team)
    return _serialize_team(team)


def _load_team_for_user(
    db: Session, team_id: uuid.UUID, user_id: uuid.UUID, user_studios=None
) -> Team:
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Équipe introuvable (§15.7 IDOR protection)",
        )
    require_resource_in_user_studio(db, user_id, team.studio_id, user_studios)
    return team


@router.get("/studios/{studio_id}/teams/{team_id}", response_model=TeamOut)
def get_team(
    studio_id: uuid.UUID,
    team_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    team = db.query(Team).filter(
        Team.id == team_id, Team.studio_id == studio_id
    ).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Équipe introuvable (§15.7 IDOR protection)",
        )
    return _serialize_team(team)


@router.put("/studios/{studio_id}/teams/{team_id}", response_model=TeamOut)
def update_team(
    studio_id: uuid.UUID,
    team_id: uuid.UUID,
    data: TeamUpdate,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    team = db.query(Team).filter(
        Team.id == team_id, Team.studio_id == studio_id
    ).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Équipe introuvable (§15.7 IDOR protection)",
        )
    if data.name is not None:
        team.name = data.name
    if data.description is not None:
        team.description = data.description
    db.commit()
    db.refresh(team)
    return _serialize_team(team)


@router.delete(
    "/studios/{studio_id}/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_team(
    studio_id: uuid.UUID,
    team_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    team = db.query(Team).filter(
        Team.id == team_id, Team.studio_id == studio_id
    ).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Équipe introuvable (§15.7 IDOR protection)",
        )
    db.delete(team)
    db.commit()
    return None


# ------------------------------------------------------------------
# Membres d'équipe
# ------------------------------------------------------------------
def _serialize_member(m: TeamMembership) -> TeamMemberOut:
    return TeamMemberOut(
        id=str(m.id),
        team_id=str(m.team_id),
        user_id=str(m.user_id),
        email=m.user.email if m.user else None,
        role=m.role,
    )


@router.get(
    "/studios/{studio_id}/teams/{team_id}/members",
    response_model=List[TeamMemberOut],
)
def list_team_members(
    studio_id: uuid.UUID,
    team_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    team = db.query(Team).filter(
        Team.id == team_id, Team.studio_id == studio_id
    ).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Équipe introuvable (§15.7 IDOR protection)",
        )
    return [_serialize_member(m) for m in team.memberships]


@router.post(
    "/studios/{studio_id}/teams/{team_id}/members",
    response_model=TeamMemberOut,
    status_code=status.HTTP_201_CREATED,
)
def add_team_member(
    studio_id: uuid.UUID,
    team_id: uuid.UUID,
    data: TeamMemberAdd,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_payload(payload)
    require_membership(db, user_id, studio_id)
    team = db.query(Team).filter(
        Team.id == team_id, Team.studio_id == studio_id
    ).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Équipe introuvable (§15.7 IDOR protection)",
        )

    target_user_id = uuid.UUID(data.user_id)
    # Anti-IDOR : l'utilisateur ajouté doit être membre du même studio
    is_member = (
        db.query(StudioMembership)
        .filter(
            StudioMembership.studio_id == studio_id,
            StudioMembership.user_id == target_user_id,
        )
        .first()
    )
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable dans ce studio (§15.7 IDOR protection)",
        )

    existing = (
        db.query(TeamMembership)
        .filter(
            TeamMembership.team_id == team.id,
            TeamMembership.user_id == target_user_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Utilisateur déjà membre de l'équipe",
        )

    membership = TeamMembership(
        team_id=team.id, user_id=target_user_id, role=data.role
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return _serialize_member(membership)


@router.delete(
    "/studios/{studio_id}/teams/{team_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_team_member(
    studio_id: uuid.UUID,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    caller_id = get_user_id_from_payload(payload)
    require_membership(db, caller_id, studio_id)
    team = db.query(Team).filter(
        Team.id == team_id, Team.studio_id == studio_id
    ).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Équipe introuvable (§15.7 IDOR protection)",
        )
    membership = (
        db.query(TeamMembership)
        .filter(
            TeamMembership.team_id == team.id,
            TeamMembership.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membre introuvable dans l'équipe (§15.7 IDOR protection)",
        )
    db.delete(membership)
    db.commit()
    return None
