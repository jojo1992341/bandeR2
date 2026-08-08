import uuid
from sqlalchemy import String, Boolean, DateTime, func, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
from datetime import datetime

class TypographicProfile(Base):
    """
    Profil typographique par studio §2.4, §8.3, §9.2, §16.3
    - codes : conventions typographiques (crochets, italique, majuscules, parenthèses...)
    - thresholds : seuils de calibrage (silence_ms, max_duration_ms, syllable_rate_...)
    Plusieurs profils possibles par studio (un par diffuseur/client).
    """
    __tablename__ = "typographic_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    studio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("studios.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Codes typographiques : dict {code: bool or config}
    # ex: {"crochets": true, "italique": true, "majuscules": false, "parentheses": true}
    codes: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    # Seuils de calibrage : dict
    # ex: {"silence_ms": 500, "max_duration_ms": 15000, "syllable_rate_min": 5.0, ...}
    thresholds: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    # Conventions supplémentaires (optionnel)
    conventions: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
