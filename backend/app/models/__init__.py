from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, JSON, Text, Float, func
from datetime import datetime
from typing import List, Optional

class Base(DeclarativeBase):
    pass

class Studio(Base):
    __tablename__ = "studios"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    users: Mapped[List["User"]] = relationship(back_populates="studio")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="guest")
    studio_id: Mapped[int] = mapped_column(ForeignKey("studios.id"))
    studio: Mapped["Studio"] = relationship(back_populates="users")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    studio_id: Mapped[int] = mapped_column(ForeignKey("studios.id"))
    status: Mapped[str] = mapped_column(String(50), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class MediaAsset(Base):
    __tablename__ = "media_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    filename: Mapped[str] = mapped_column(String(255))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(500))

class RythmoBand(Base):
    __tablename__ = "rythmo_bands"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    status: Mapped[str] = mapped_column(String(50), default="draft")

class Replica(Base):
    __tablename__ = "replicas"
    id: Mapped[int] = mapped_column(primary_key=True)
    rythmo_band_id: Mapped[int] = mapped_column(ForeignKey("rythmo_bands.id"))
    order_index: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    speaker_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

print("✅ Core models defined")
