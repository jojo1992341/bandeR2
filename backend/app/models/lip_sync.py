import uuid
from sqlalchemy import Float, Integer, String, Boolean, DateTime, func, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
from datetime import datetime

class LipSyncFrame(Base):
    """Frame de courbe d'activité labiale §8.2.6, §11.4
    Mesure image par image de l'ouverture buccale via FaceMesh
    """
    __tablename__ = "lip_sync_frames"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    media_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp_ms: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Ouverture labiale normalisée 0.0 (fermé) à 1.0 (ouvert max)
    opening: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Confiance détection FaceMesh 0-1
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Visage visible sur ce plan
    face_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Gros plan (visage occupant > seuil de l'image)
    is_close_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Distance inter-commissures ou autre métrique brute (optionnel)
    raw_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Face bounding box normalisée (optionnel, JSON)
    face_bbox: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class LipSyncResult(Base):
    """Résultat agrégé de synchronisation labiale pour un média (courbe + métadonnées)"""
    __tablename__ = "lip_sync_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    media_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    fps: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    face_visible_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    close_up_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Courbe complète en JSON pour accès rapide : [{t, opening, visible, confidence, close_up}, ...]
    curve: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Métadonnées de détection
    detector_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Feature flag utilisé
    feature_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
