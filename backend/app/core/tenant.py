"""
Helpers d'isolation multi-tenant (studios) — §15.7 IDOR protection & §16.3 CDC.

Centralise les vérifications d'appartenance d'un utilisateur à un studio afin que
toutes les ressources studio-scopées (dossiers, tags, équipes, tâches...) appliquent
la même politique anti-IDOR :

- Un utilisateur n'accède qu'aux studios dont il est membre (`StudioMembership`).
- L'accès à une ressource par identifiant vérifie que `resource.studio_id` figure
  parmi les studios de l'utilisateur, sinon la ressource est invisible (404) — on
  ne fuite jamais l'existence d'une ressource appartenant à un autre tenant.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Set

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import StudioMembership


def get_user_studio_ids(db: Session, user_id: uuid.UUID) -> Set[uuid.UUID]:
    """Retourne l'ensemble des studio_id dont l'utilisateur est membre."""
    rows = (
        db.query(StudioMembership.studio_id)
        .filter(StudioMembership.user_id == user_id)
        .all()
    )
    return {r[0] for r in rows}


def is_studio_member(
    db: Session, user_id: uuid.UUID, studio_id: uuid.UUID
) -> bool:
    """Vrai si l'utilisateur est membre du studio."""
    return (
        db.query(StudioMembership)
        .filter(
            StudioMembership.studio_id == studio_id,
            StudioMembership.user_id == user_id,
        )
        .first()
        is not None
    )


def require_membership(
    db: Session, user_id: uuid.UUID, studio_id: uuid.UUID
) -> None:
    """
    Lève 403 si l'utilisateur n'est pas membre du studio.
    Utilisé pour les opérations de collection (list/create) où l'on connaît le
    studio cible via le chemin de l'URL.
    """
    if not is_studio_member(db, user_id, studio_id):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : vous n'êtes pas membre de ce studio (§15.7 IDOR protection)",
        )


def require_resource_in_user_studio(
    db: Session,
    user_id: uuid.UUID,
    resource_studio_id: uuid.UUID,
    user_studio_ids: Iterable[uuid.UUID] | None = None,
) -> None:
    """
    Vérifie qu'une ressource appartient à un studio de l'utilisateur.

    Lève 404 (et non 403) pour ne pas divulguer l'existence d'une ressource d'un
    autre tenant — politique anti-IDOR stricte (§15.7).
    """
    studios = (
        set(user_studio_ids)
        if user_studio_ids is not None
        else get_user_studio_ids(db, user_id)
    )
    if resource_studio_id not in studios:
        raise HTTPException(
            status_code=404,
            detail="Ressource introuvable (§15.7 IDOR protection)",
        )


def get_user_id_from_payload(payload: dict) -> uuid.UUID:
    """Extrait et valide le `sub` d'un payload JWT."""
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return uuid.UUID(str(sub))
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid user id")
