import uuid
import hashlib
from sqlalchemy import String, Integer, Float, DateTime, func, ForeignKey, JSON, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
from app.core.uuid7 import uuid7
from datetime import datetime
from typing import Optional

class AnonymizedCorrection(Base):
    """
    §8.5 — Journalisation anonymisée des corrections manuelles
    Chaque correction manuelle (recalage mot, correction locuteur, changement code typo)
    est journalisée de façon anonymisée si le studio a consenti, pour constituer
    un corpus d'entraînement des modèles heuristiques (prosodie, émotion).
    Jamais de réentraînement des modèles de fondation tiers (Whisper, pyannote) hors licence.
    """
    __tablename__ = "anonymized_corrections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    studio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("studios.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    media_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=True, index=True)

    # Type de correction : word_realign, speaker_correction, typo_code_change
    correction_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Données anonymisées : pas de texte brut, pas d'email, pas d'IP
    # Pour word_realign : {word_hash, duration_delta_ms, start_delta_ms, end_delta_ms, original_duration, corrected_duration, confidence_before}
    # Pour speaker_correction : {original_speaker_hash, corrected_speaker_hash, num_words_affected}
    # Pour typo_code_change : {original_typo_hash, corrected_typo_hash, added_codes, removed_codes}
    correction_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)

    # Hashes pour traçabilité sans PII
    original_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    corrected_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Heuristique cible : prosody, emotion, diarization
    heuristic_target: Mapped[str | None] = mapped_column(String(50), nullable=True, default="prosody")

    # Métadonnées anonymisées
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True, default="heuristic-v1")

    # Garantie d'anonymisation
    is_anonymized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Pas de user_id/email/ip stocké — anonymisé
    # On stocke seulement un hash du studio/user pour déduplication si besoin, mais pas réversible
    anonymized_studio_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    anonymized_user_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    @staticmethod
    def hash_value(value: str) -> str:
        """Anonymisation par hachage SHA256 (non réversible)."""
        if not value:
            return ""
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]  # 16 chars suffisent pour anonymat

    @staticmethod
    def hash_studio_id(studio_id: uuid.UUID) -> str:
        return hashlib.sha256(str(studio_id).encode()).hexdigest()[:16]

    @staticmethod
    def hash_user_id(user_id: uuid.UUID) -> str:
        return hashlib.sha256(str(user_id).encode()).hexdigest()[:16]

    def to_dict(self):
        return {
            "id": str(self.id),
            "studio_id": str(self.studio_id),
            "project_id": str(self.project_id) if self.project_id else None,
            "media_id": str(self.media_id) if self.media_id else None,
            "correction_type": self.correction_type,
            "correction_data": self.correction_data or {},
            "original_hash": self.original_hash,
            "corrected_hash": self.corrected_hash,
            "heuristic_target": self.heuristic_target,
            "model_version": self.model_version,
            "is_anonymized": self.is_anonymized,
            "consent_given": self.consent_given,
            "anonymized_studio_hash": self.anonymized_studio_hash,
            "anonymized_user_hash": self.anonymized_user_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
