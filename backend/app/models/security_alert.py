import uuid
from sqlalchemy import String, JSON, DateTime, func, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
from typing import Optional


class SecurityAlert(Base):
    """
    Alertes automatiques sur comportements anormaux (§15.5) :
    téléchargements massifs, connexions depuis des géolocalisations inhabituelles, etc.
    """

    __tablename__ = "security_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    alert_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    user_email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    studio_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    details: Mapped[dict | None] = mapped_column(JSON, default=dict)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
