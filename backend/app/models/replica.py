"""
Entité Replica (§9.4 CDC)

Représente une réplique de dialogue dans une bande rythmo.
Chaque réplique appartient à une RythmoBand (et par extension à un projet).

Relation: RythmoBand → Replica (1:N)

Note: media_id est conservé pour la migration progressive.
Dans le futur, seul rythmo_band_id sera utilisé.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, TYPE_CHECKING, Optional

from sqlalchemy import (
    String,
    Integer,
    Numeric,
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

if TYPE_CHECKING:
    from .comment import Comment
    from .rythmo_band import RythmoBand
    from .media_asset import MediaAsset
    from .speaker import Speaker


class Replica(Base):
    __tablename__ = "replicas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Relation vers la bande rythmo (NOUVEAU - §9.2)
    rythmo_band_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rythmo_bands.id"),
        nullable=True,
        index=True
    )
    # media_id conservé pour migration progressive (déprécié dans le futur)
    media_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_assets.id"),
        nullable=False,
        index=True
    )
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("speakers.id"), nullable=True, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    typo_codes: Mapped[dict | None] = mapped_column(JSON, default=dict)
    confidence_score: Mapped[float] = mapped_column(
        Numeric(4, 3), nullable=True, default=0.0
    )
    is_manually_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    breath_marker: Mapped[bool] = mapped_column(Boolean, default=False)
    syllable_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0
    )
    speech_rate: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True, default=0.0
    )
    speech_rate_alert: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    # §16.4 optimistic lock counter
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relations
    rythmo_band: Mapped["RythmoBand | None"] = relationship(
        "RythmoBand",
        back_populates="replicas",
        lazy="selectin"
    )
    media_asset: Mapped["MediaAsset"] = relationship("MediaAsset")
    speaker: Mapped["Speaker | None"] = relationship("Speaker")
    comments: Mapped[List["Comment"]] = relationship(
        back_populates="replica", cascade="all, delete-orphan"
    )

    def __str__(self) -> str:
        preview = self.text[:30] + "..." if len(self.text) > 30 else self.text
        return f"Replica(id={self.id.hex[:8]}, '{preview}')"
