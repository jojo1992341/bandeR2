"""
Entité RythmoBand (§9.2–§9.4 CDC)

Représente une bande rythmo avec versionnage. Une bande appartient à un projet
et contient des répliques. Chaque modification crée une nouvelle version.

Relation: Project → RythmoBand → Replica

TODO: Dans le futur, Replica.media_id sera déprécié au profit de rythmo_band_id
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    func,
    ForeignKey,
    Text,
    JSON,
    Boolean,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class RythmoBandStatus:
    """Statuts possibles pour une RythmoBand (§9.3 lifecycle)."""
    DRAFT = "draft"           # En cours de création
    REVIEW = "review"         # En révision
    VALIDATED = "validated"   # Validée
    ARCHIVED = "archived"     # Archivée


class RythmoBand(Base):
    """
    Entité RythmoBand (§9.2).
    
    Une bande rythmo représente une version complète de la synchronisation
    labiale pour un média donné. Chaque bande a un numéro de version et un statut.
    
    Relations:
        Project → RythmoBand (1:N)
        RythmoBand → Replica (1:N)
    """
    __tablename__ = "rythmo_bands"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_assets.id"), nullable=True, index=True
    )
    version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=RythmoBandStatus.DRAFT, index=True
    )
    title: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    typographic_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("typographic_profiles.id"), nullable=True, index=True
    )
    is_master: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    band_metadata: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        default=dict
    )

    # Relations
    project: Mapped["Project"] = relationship("Project", back_populates="rythmo_bands")
    media_asset: Mapped["MediaAsset | None"] = relationship("MediaAsset")
    typographic_profile: Mapped["TypographicProfile | None"] = relationship("TypographicProfile")
    replicas: Mapped[List["Replica"]] = relationship(
        "Replica",
        back_populates="rythmo_band",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def __str__(self) -> str:
        return f"RythmoBand(id={self.id.hex[:8]}, v{self.version_number}, {self.status})"


# Import en retard pour éviter la boucle
from app.models.project import Project  # noqa: E402
from app.models.media_asset import MediaAsset  # noqa: E402
from app.models.typographic_profile import TypographicProfile  # noqa: E402
