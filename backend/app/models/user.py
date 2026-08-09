import uuid
from sqlalchemy import String, Boolean, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base
from app.core.uuid7 import uuid7
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .comment import Comment
    from .user_preferences import UserPreferences
    from .team import TeamMembership
    from .task import Task


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, default=None
    )
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[List["StudioMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    comments_authored: Mapped[List["Comment"]] = relationship(
        back_populates="author"
    )
    # §16.2 — préférences d'affichage (thème, langue, raccourcis)
    preferences: Mapped[Optional["UserPreferences"]] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # §16.3 — appartenances aux équipes (sous-groupes studio)
    team_memberships: Mapped[List["TeamMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    # §16.2 — tâches (Vue « Mon activité »)
    assigned_tasks: Mapped[List["Task"]] = relationship(
        foreign_keys="Task.assignee_id", back_populates="assignee"
    )
    created_tasks: Mapped[List["Task"]] = relationship(
        foreign_keys="Task.created_by", back_populates="creator"
    )
