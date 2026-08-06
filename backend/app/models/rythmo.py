from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Text, ForeignKey, JSON
from app.models import Base
from typing import List, Optional

class RythmoBand(Base):
    __tablename__ = "rythmo_bands"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    status: Mapped[str] = mapped_column(String(50), default="draft")
    replicas: Mapped[List["Replica"]] = relationship(back_populates="rythmo_band", cascade="all, delete-orphan")

class Replica(Base):
    __tablename__ = "replicas"
    id: Mapped[int] = mapped_column(primary_key=True)
    rythmo_band_id: Mapped[int] = mapped_column(ForeignKey("rythmo_bands.id"))
    order_index: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    speaker_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[float] = mapped_column(default=0.85)
    codes: Mapped[dict] = mapped_column(JSON, default={})
    
    rythmo_band: Mapped["RythmoBand"] = relationship(back_populates="replicas")
