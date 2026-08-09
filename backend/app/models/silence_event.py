import uuid
from sqlalchemy import String, Integer, Float, DateTime, JSON, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
from app.core.uuid7 import uuid7
from datetime import datetime
from typing import Optional


class SilenceEvent(Base):
    """
    Événement de silence classifié (§8.2.4, §9.2) :
    - respiration audible (pic d'énergie hautes fréquences avant reprise)
    - pause syntaxique (silence > 300 ms en fin de proposition)
    - hésitation (micro-silence < 200 ms suivi d'une reprise du même locuteur)
    - coupe technique (silence total, absence de signal)
    """

    __tablename__ = "silence_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_assets.id"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=0.90
    )
    details: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
