import uuid
from sqlalchemy import String, Integer, Numeric, DateTime, func, ForeignKey, Text, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base
from typing import List, TYPE_CHECKING
if TYPE_CHECKING:
    from .comment import Comment

class Replica(Base):
    __tablename__ = "replicas"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    media_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("media_assets.id"), nullable=False, index=True)
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("speakers.id"), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    typo_codes: Mapped[dict | None] = mapped_column(JSON, default=dict)
    confidence_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=True, default=0.0)
    is_manually_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    breath_marker: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # §16.4 optimistic lock counter
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    comments: Mapped[List["Comment"]] = relationship(back_populates="replica", cascade="all, delete-orphan")
