"""
Entités Équipes / sous-groupes (§16.3 CDC — Gestion des studios multi-tenant)

« Gestion des sous-groupes/équipes au sein d'un grand studio (ex. « Pôle
jeunesse », « Pôle films ») avec droits d'accès dédiés — fonctionnalité plan
Enterprise. »

- Team : équipe studio-scopée.
- TeamMembership : appartenance d'un utilisateur à une équipe (avec rôle intra-équipe).

Isolation stricte par studio (tenant) : une équipe et ses membres n'appartiennent
qu'à un seul studio. Aucun tenant ne peut lister, lire ou modifier les équipes
d'un autre studio (§15.7 IDOR protection).
"""

from __future__ import annotations

import uuid
from app.core.uuid7 import uuid7
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import String, DateTime, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from .studio import Studio
    from .user import User


class Team(Base):
    """Sous-groupe / équipe au sein d'un studio (plan Enterprise)."""

    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("studio_id", "name", name="uq_team_studio_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    studio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("studios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    studio: Mapped["Studio"] = relationship()
    memberships: Mapped[List["TeamMembership"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class TeamMembership(Base):
    """Appartenance d'un utilisateur à une équipe (rôle intra-équipe)."""

    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(50), default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    team: Mapped["Team"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="team_memberships")
