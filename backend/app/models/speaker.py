import uuid
from sqlalchemy import String, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
from app.core.uuid7 import uuid7

class Speaker(Base):
    __tablename__ = "speakers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False, default="Locuteur")
    color: Mapped[str] = mapped_column(String(7), default="#e11d48")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
