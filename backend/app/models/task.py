"""
Entité Task (§16.2 CDC — Vue « Mon activité »)

« Vue "Mon activité" récapitulant les projets récents et les tâches assignées. »

Une tâche est assignée à un utilisateur, rattachée à un projet et isolée dans un
studio (tenant). Elle alimente la vue d'activité de l'utilisateur assigné.
"""

from __future__ import annotations

import uuid
from app.core.uuid7 import uuid7
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from .studio import Studio
    from .user import User
    from .project import Project


# Statuts du cycle de vie d'une tâche
TASK_STATUSES = ("à_faire", "en_cours", "terminée", "annulée")
DEFAULT_TASK_STATUS = "à_faire"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    studio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("studios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=DEFAULT_TASK_STATUS, index=True
    )
    # Utilisateur assigné (peut être null = non assignée)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    due_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    studio: Mapped["Studio"] = relationship()
    project: Mapped[Optional["Project"]] = relationship()
    assignee: Mapped[Optional["User"]] = relationship(
        foreign_keys=[assignee_id], back_populates="assigned_tasks"
    )
    creator: Mapped[Optional["User"]] = relationship(
        foreign_keys=[created_by], back_populates="created_tasks"
    )
