import uuid
from sqlalchemy import String, Float, Integer, DateTime, func, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base
from datetime import datetime
from typing import Optional


class EmotionTag(Base):
    """
    Étiquette émotionnelle / intention §8.2.5 & §9.2
    Double analyse :
      - (a) acoustique (prosodie, timbre, énergie) via wav2vec2 fine-tuné → émotion perçue
      - (b) textuelle (NLP FR) → intention de la réplique
    Stockée à titre indicatif, n'altère jamais le texte de la réplique,
    seulement codes typographiques suggérés.
    """

    __tablename__ = "emotion_tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    replica_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("replicas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # optionnel : lien direct au média/projet pour requêtes rapides
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # type du tag : emotion | intention | combined (pour compatibilité)
    tag_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # label principal (ex: joie, colere, tristesse, peur, surprise, neutre / affirmation, question, ordre, hesitation, exclamation)
    label: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.85)
    # source : audio (wav2vec2) | texte (NLP FR) | mixte
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="audio")
    # codes typographiques suggérés (indicatif) — ne modifie jamais Replica.text automatiquement
    suggested_typo_codes: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    # détails complémentaires (features acoustiques, tokens NLP, version modèle, etc.)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relation vers réplique (lazy)
    replica: Mapped[Optional["Replica"]] = relationship("Replica", backref="emotion_tags")
