"""
Entité UserPreferences (§16.2 CDC — Gestion des utilisateurs)

Profil utilisateur : préférences d'affichage (thème, raccourcis personnalisés),
langue d'interface.

Relation 1:1 avec User. Les préférences sont propres à l'utilisateur (et non au
studio) : elles le suivent quel que soit le studio actif.
"""

from __future__ import annotations

import uuid
from app.core.uuid7 import uuid7
from datetime import datetime

from sqlalchemy import String, DateTime, func, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, TYPE_CHECKING

from app.models.base import Base

if TYPE_CHECKING:
    from .user import User


VALID_THEMES = ("light", "dark", "system")
DEFAULT_THEME = "system"
DEFAULT_LANGUAGE = "fr"


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_preferences_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Thème d'affichage : light | dark | system
    theme: Mapped[str] = mapped_column(String(20), default=DEFAULT_THEME)
    # Langue d'interface (code BCP-47, ex. fr, en, es)
    language: Mapped[str] = mapped_column(String(10), default=DEFAULT_LANGUAGE)
    # Raccourcis clavier personnalisés (ex. {"save": "Ctrl+S", ...})
    custom_shortcuts: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[Optional["User"]] = relationship(back_populates="preferences")
