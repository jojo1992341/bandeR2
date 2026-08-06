from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, JSON, ForeignKey, Boolean
from app.models import Base
from typing import Dict, Any

class TypographicProfile(Base):
    __tablename__ = "typographic_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    studio_id: Mapped[int] = mapped_column(ForeignKey("studios.id"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    rules: Mapped[Dict[str, Any]] = mapped_column(JSON)  # e.g. {"use_brackets": true, "capitalize": true, ...}
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
