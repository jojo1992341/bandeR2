"""
API Préférences utilisateur (§16.2 CDC)

Profil utilisateur : préférences d'affichage (thème, raccourcis personnalisés),
langue d'interface. Les préférences sont propres à l'utilisateur authentifié
(`/me`) — un utilisateur ne peut consulter ou modifier que ses propres
préférences (anti-IDOR).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import get_current_user_payload
from app.core.tenant import get_user_id_from_payload
from app.models import UserPreferences
from app.models.user_preferences import VALID_THEMES, DEFAULT_THEME, DEFAULT_LANGUAGE

router = APIRouter()


class PreferencesOut(BaseModel):
    id: str
    user_id: str
    theme: str
    language: str
    custom_shortcuts: dict


class PreferencesUpdate(BaseModel):
    theme: Optional[str] = None
    language: Optional[str] = None
    custom_shortcuts: Optional[dict] = Field(default=None)


def _get_or_create(db: Session, user_id: uuid.UUID) -> UserPreferences:
    prefs = (
        db.query(UserPreferences)
        .filter(UserPreferences.user_id == user_id)
        .first()
    )
    if not prefs:
        prefs = UserPreferences(
            user_id=user_id,
            theme=DEFAULT_THEME,
            language=DEFAULT_LANGUAGE,
            custom_shortcuts={},
        )
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


def _serialize(prefs: UserPreferences) -> PreferencesOut:
    return PreferencesOut(
        id=str(prefs.id),
        user_id=str(prefs.user_id),
        theme=prefs.theme,
        language=prefs.language,
        custom_shortcuts=prefs.custom_shortcuts or {},
    )


@router.get("/me/preferences", response_model=PreferencesOut)
def get_my_preferences(
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Retourne les préférences de l'utilisateur authentifié (crée des valeurs par défaut)."""
    user_id = get_user_id_from_payload(payload)
    prefs = _get_or_create(db, user_id)
    return _serialize(prefs)


@router.put("/me/preferences", response_model=PreferencesOut)
def update_my_preferences(
    data: PreferencesUpdate,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    """Met à jour les préférences de l'utilisateur authentifié."""
    user_id = get_user_id_from_payload(payload)
    prefs = _get_or_create(db, user_id)

    if data.theme is not None:
        if data.theme not in VALID_THEMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Thème invalide (valeurs: {', '.join(VALID_THEMES)})",
            )
        prefs.theme = data.theme
    if data.language is not None:
        if not data.language.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La langue ne peut pas être vide",
            )
        prefs.language = data.language.strip()
    if data.custom_shortcuts is not None:
        if not isinstance(data.custom_shortcuts, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="custom_shortcuts doit être un objet JSON",
            )
        prefs.custom_shortcuts = data.custom_shortcuts

    db.commit()
    db.refresh(prefs)
    return _serialize(prefs)
