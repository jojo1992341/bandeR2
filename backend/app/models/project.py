"""
Entité Project (§16.1 CDC)

Représente un projet de synchronisation labiale.
Un projet contient des médias et des bandes rythmo.

Relations:
    Studio → Project (1:N)
    Project → MediaAsset (1:N)
    Project → RythmoBand (1:N)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, TYPE_CHECKING

from sqlalchemy import String, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


if TYPE_CHECKING:
    from .studio import Studio
    from .media_asset import MediaAsset
    from .rythmo_band import RythmoBand, RythmoBandStatus


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    studio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("studios.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_lang: Mapped[str | None] = mapped_column(String(10), default="fr")
    target_lang: Mapped[str | None] = mapped_column(String(10), default="fr")
    status: Mapped[str] = mapped_column(
        String(50), default="Cree", index=True
    )  # §16.1 lifecycle
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relations
    studio: Mapped["Studio"] = relationship(back_populates="projects")
    media_assets: Mapped[List["MediaAsset"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan"
    )
    rythmo_bands: Mapped[List["RythmoBand"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def get_master_band(self) -> "RythmoBand | None":
        """
        Retourne la bande maître du projet.
        
        Note: Nécessite que rythmo_bands soit chargé (selectinload ou joinedload).
        """
        for band in self.rythmo_bands:
            if band.is_master:
                return band
        return None

    def get_latest_validated_band(self) -> "RythmoBand | None":
        """
        Retourne la dernière bande validée.
        
        Note: Nécessite que rythmo_bands soit chargé (selectinload ou joinedload).
        """
        from app.models.rythmo_band import RythmoBandStatus
        
        validated = [b for b in self.rythmo_bands if b.status == RythmoBandStatus.VALIDATED]
        if not validated:
            return None
        return max(validated, key=lambda b: b.version_number)
