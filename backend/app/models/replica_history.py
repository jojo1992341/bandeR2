import uuid
from sqlalchemy import String, Integer, Text, DateTime, func, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

class ReplicaHistory(Base):
    __tablename__ = "replica_history"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    replica_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("replicas.id"), nullable=False, index=True)
    previous_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    previous_start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    previous_end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    previous_speaker_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("speakers.id"), nullable=True)
    updated_by: Mapped[str] = mapped_column(String(255), default="system")
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
