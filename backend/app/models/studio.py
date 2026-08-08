import uuid
from sqlalchemy import String, JSON, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base
from typing import List


class Studio(Base):
    __tablename__ = "studios"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    plan: Mapped[str | None] = mapped_column(String(50), default="free")
    custom_typographic_profiles: Mapped[dict | None] = mapped_column(
        JSON, default=dict
    )
    quotas: Mapped[dict | None] = mapped_column(JSON, default=dict)
    security_settings: Mapped[dict | None] = mapped_column(
        JSON,
        default=lambda: {
            "watermark_enabled": True,
            "encryption_at_rest_enabled": True,
            "encryption_in_transit_enabled": True,
            "auto_purge_enabled": True,
            "retention_days": 30,
        },
    )
    # §8.5 Feedback loop — consentement contractuel studio pour journalisation anonymisée
    feedback_settings: Mapped[dict | None] = mapped_column(
        JSON,
        default=lambda: {
            "enabled": False,
            "consented_at": None,
            "consented_by": None,
            "version": 1,
        },
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[List["StudioMembership"]] = relationship(
        back_populates="studio"
    )
    projects: Mapped[List["Project"]] = relationship(back_populates="studio")
