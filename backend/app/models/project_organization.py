"""
Entités d'organisation des projets (§16.1 CDC — Gestion des projets)

« Système de tags et de dossiers pour organiser les projets par client, saison,
diffuseur. »

- ProjectFolder : dossiers (imbriqués) studio-scopés.
- ProjectTag : tags studio-scopés (ex. client, saison, diffuseur).
- project_tags : association M:N entre projets et tags.

Toutes ces entités sont strictement isolées par studio (tenant) : `studio_id`
obligatoire + filtrage applicatif systématique (§15.7 IDOR protection).
"""

from __future__ import annotations

import uuid
from app.core.uuid7 import uuid7
from datetime import datetime

from sqlalchemy import (
    String,
    DateTime,
    func,
    ForeignKey,
    UniqueConstraint,
    Table,
    Column,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, Optional, TYPE_CHECKING

from app.models.base import Base

if TYPE_CHECKING:
    from .studio import Studio
    from .project import Project


# Table d'association M:N Project ↔ ProjectTag
project_tags = Table(
    "project_tags",
    Base.metadata,
    Column(
        "project_id",
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        UUID(as_uuid=True),
        ForeignKey("project_tags_def.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class ProjectFolder(Base):
    """Dossier d'organisation des projets (imbriqué via parent_folder_id)."""

    __tablename__ = "project_folders"
    __table_args__ = (
        UniqueConstraint(
            "studio_id", "name", "parent_folder_id", name="uq_folder_studio_name_parent"
        ),
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Dossier parent (null = racine). Imbrication autorisée au sein du même studio.
    parent_folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
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
    parent: Mapped[Optional["ProjectFolder"]] = relationship(
        remote_side="ProjectFolder.id", back_populates="children"
    )
    children: Mapped[List["ProjectFolder"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class ProjectTag(Base):
    """Tag studio-scopé pour catégoriser les projets (client, saison, diffuseur…)."""

    __tablename__ = "project_tags_def"
    __table_args__ = (
        UniqueConstraint("studio_id", "name", name="uq_tag_studio_name"),
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
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#6366f1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    studio: Mapped["Studio"] = relationship()
    projects: Mapped[List["Project"]] = relationship(
        secondary=project_tags, back_populates="tags"
    )
