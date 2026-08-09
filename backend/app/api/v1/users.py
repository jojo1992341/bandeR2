"""
Ressource Users (CDC §10.2 & §16.2).

Endpoints exposés (contrat OpenAPI) :
- Self-service (utilisateur authentifié) :
  - GET    /users/me            → profil complet (membres, préférences, MFA)
  - PATCH  /users/me            → mise à jour profil (email, mot de passe)
  - POST   /users/me/deactivate → désactivation du compte (révoque les sessions)
  - DELETE /users/me            → suppression conforme RGPD
- Administration (rôle owner/admin, **scopé au studio**) :
  - GET    /users               → liste des utilisateurs des studios administrés
  - GET    /users/{user_id}     → consultation d'un utilisateur
  - PATCH  /users/{user_id}/status → activation/désactivation
  - DELETE /users/{user_id}     → suppression RGPD par un admin

Toute opération administrative est **isolée par studio** : un admin d'un studio
ne peut consulter ni gérer un utilisateur qui n'appartient pas à l'un de ses
studios (anti-IDOR inter-studios, §15.7).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.auth_handler import create_access_token
from app.core.database import get_db
from app.core.password import hash_password, verify_password
from app.core.pwned import check_pwned_password
from app.core.rbac import get_current_user_payload, normalize_role
from app.core.tenant import get_user_id_from_payload
from app.models import (
    Comment,
    Studio,
    StudioMembership,
    Task,
    User,
    UserPreferences,
)

router = APIRouter()


# ------------------------------------------------------------------
# Schémas (contrat OpenAPI)
# ------------------------------------------------------------------
class MembershipOut(BaseModel):
    studio_id: str
    studio_name: str
    role: str


class PreferencesSummary(BaseModel):
    theme: str
    language: str


class UserProfileOut(BaseModel):
    id: str
    email: EmailStr
    role: str
    is_active: bool
    totp_enabled: bool
    created_at: Optional[datetime]
    memberships: List[MembershipOut]
    preferences: Optional[PreferencesSummary]


class UserUpdateIn(BaseModel):
    email: Optional[EmailStr] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None


class UserDeactivateOut(BaseModel):
    status: str
    user_id: str
    is_active: bool
    message: str


class UserStatusIn(BaseModel):
    is_active: bool


class UserListItem(BaseModel):
    id: str
    email: EmailStr
    role: str
    is_active: bool


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _load_user(db: Session, payload: dict) -> User:
    user_id = get_user_id_from_payload(payload)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _serialize_profile(user: User) -> UserProfileOut:
    memberships = [
        MembershipOut(
            studio_id=str(m.studio_id),
            studio_name=m.studio.name if m.studio else "",
            role=m.role,
        )
        for m in user.memberships
    ]
    prefs = None
    if getattr(user, "preferences", None):
        prefs = PreferencesSummary(
            theme=user.preferences.theme, language=user.preferences.language
        )
    return UserProfileOut(
        id=str(user.id),
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        totp_enabled=getattr(user, "totp_enabled", False),
        created_at=user.created_at,
        memberships=memberships,
        preferences=prefs,
    )


def _admin_studio_ids(user: User) -> set:
    """Studios où `user` détient un rôle d'administration."""
    global_admin = normalize_role(user.role) in ("owner", "admin")
    ids = set()
    for m in user.memberships:
        if global_admin or normalize_role(m.role) in ("owner", "admin"):
            ids.add(m.studio_id)
    return ids


def _load_target_for_admin(db: Session, admin: User, target_id: uuid.UUID) -> User:
    """Charge un utilisateur cible en vérifiant qu'il partage un studio administré."""
    target = db.query(User).filter(User.id == target_id).first()
    if not target:
        raise HTTPException(
            status_code=404, detail="Utilisateur introuvable (§15.7 IDOR protection)"
        )
    admin_studios = _admin_studio_ids(admin)
    target_studios = {m.studio_id for m in target.memberships}
    if not (admin_studios & target_studios):
        raise HTTPException(
            status_code=403,
            detail="Utilisateur hors de vos studios (§15.7 isolation inter-studios)",
        )
    return target


# ------------------------------------------------------------------
# Self-service
# ------------------------------------------------------------------
def _delete_user(db: Session, user: User) -> None:
    """
    Suppression conforme RGPD : memberships/préférences/équipes sont supprimés
    en cascade par l'ORM (delete-orphan) ; on annule les références nullable
    (commentaires, tâches) avant la suppression de l'utilisateur.
    """
    uid = user.id
    db.query(Comment).filter(Comment.author_id == uid).update(
        {Comment.author_id: None}, synchronize_session=False
    )
    db.query(Task).filter(Task.assignee_id == uid).update(
        {Task.assignee_id: None}, synchronize_session=False
    )
    db.query(Task).filter(Task.created_by == uid).update(
        {Task.created_by: None}, synchronize_session=False
    )
    db.delete(user)
    db.commit()


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/me", response_model=UserProfileOut)
def get_my_profile(
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Profil complet de l'utilisateur authentifié."""
    user = _load_user(db, payload)
    return _serialize_profile(user)


@router.patch("/me", response_model=UserProfileOut)
def update_my_profile(
    data: UserUpdateIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Met à jour l'email et/ou le mot de passe de l'utilisateur authentifié."""
    user = _load_user(db, payload)

    if data.email is not None and data.email.lower() != user.email.lower():
        existing = (
            db.query(User).filter(User.email.ilike(data.email)).first()
        )
        if existing and existing.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cet email est déjà utilisé",
            )
        user.email = data.email

    if data.new_password is not None:
        if not data.current_password or not verify_password(
            data.current_password, user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Mot de passe actuel invalide",
            )
        if check_pwned_password(data.new_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mot de passe compromis (HIBP)",
            )
        user.hashed_password = hash_password(data.new_password)

    db.commit()
    db.refresh(user)
    return _serialize_profile(user)


@router.post("/me/deactivate", response_model=UserDeactivateOut)
def deactivate_my_account(
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Désactive le compte (is_active=False) et révoque toutes les sessions."""
    user = _load_user(db, payload)
    user.is_active = False
    user.token_version = (getattr(user, "token_version", 0) or 0) + 1
    db.commit()
    db.refresh(user)
    return UserDeactivateOut(
        status="deactivated",
        user_id=str(user.id),
        is_active=False,
        message="Compte désactivé et sessions révoquées",
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_account(
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Suppression conforme RGPD du propre compte."""
    user = _load_user(db, payload)
    _delete_user(db, user)
    return None


# ------------------------------------------------------------------
# Administration (scopée studio)
# ------------------------------------------------------------------
def _require_admin(payload: dict) -> None:
    if normalize_role(payload.get("role", "invité")) not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Réservé aux administrateurs (owner/admin)",
        )


@router.get("", response_model=List[UserListItem])
@router.get("/", response_model=List[UserListItem])
def list_users(
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Liste les utilisateurs des studios administrés par l'appelant."""
    admin = _load_user(db, payload)
    _require_admin(payload)
    studio_ids = _admin_studio_ids(admin)
    if not studio_ids:
        return []
    user_ids = {
        m.user_id
        for m in db.query(StudioMembership)
        .filter(StudioMembership.studio_id.in_(studio_ids))
        .all()
    }
    users = (
        db.query(User)
        .filter(User.id.in_(user_ids))
        .order_by(User.email)
        .all()
    )
    return [
        UserListItem(
            id=str(u.id), email=u.email, role=u.role, is_active=u.is_active
        )
        for u in users
    ]


@router.get("/{user_id}", response_model=UserProfileOut)
def get_user(
    user_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Consulte le profil d'un utilisateur (admin, même studio)."""
    admin = _load_user(db, payload)
    _require_admin(payload)
    target = _load_target_for_admin(db, admin, user_id)
    return _serialize_profile(target)


@router.patch("/{user_id}/status", response_model=UserDeactivateOut)
def update_user_status(
    user_id: uuid.UUID,
    data: UserStatusIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Active/désactive un utilisateur (admin, même studio)."""
    admin = _load_user(db, payload)
    _require_admin(payload)
    target = _load_target_for_admin(db, admin, user_id)
    target.is_active = data.is_active
    if not data.is_active:
        # Désactivation → révocation des sessions
        target.token_version = (getattr(target, "token_version", 0) or 0) + 1
    db.commit()
    db.refresh(target)
    return UserDeactivateOut(
        status="active" if data.is_active else "deactivated",
        user_id=str(target.id),
        is_active=target.is_active,
        message=f"Utilisateur {'activé' if data.is_active else 'désactivé'}",
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Suppression RGPD d'un utilisateur par un admin (même studio)."""
    admin = _load_user(db, payload)
    _require_admin(payload)
    target = _load_target_for_admin(db, admin, user_id)
    _delete_user(db, target)
    return None
