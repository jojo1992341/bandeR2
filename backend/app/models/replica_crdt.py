import uuid
from sqlalchemy import String, Integer, DateTime, func, ForeignKey, Text, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
from datetime import datetime
from typing import Optional, List, Dict, Any

class ReplicaCrdtState(Base):
    """
    §16.4 — État CRDT pour édition collaborative caractère par caractère
    Remplace le verrouillage optimiste par réplique là où le volume d'usage le justifie (V2)

    Stocke l'état du document CRDT pour une réplique :
    - characters : liste triée de caractères avec identifiants uniques (position, site, compteur)
    - version_vector : horloge vectorielle par site
    - site_counters : compteur par site pour génération d'IDs
    """
    __tablename__ = "replica_crdt_states"

    replica_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("replicas.id", ondelete="CASCADE"), primary_key=True)
    # État du document : liste de caractères avec métadonnées CRDT
    # Format: [{"char": "H", "id": {"site": "site-A", "counter": 1}, "pos": [0, 5], "visible": true}, ...]
    characters: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # Version vector : {site_id: counter}
    version_vector: Mapped[Dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    # Compteur global pour ce document
    clock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Texte matérialisé (dérivé des characters visibles, pour recherche et export)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Métadonnées
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class ReplicaCrdtOperation(Base):
    """
    Journal des opérations CRDT pour une réplique
    Permet la convergence et l'audit
    """
    __tablename__ = "replica_crdt_operations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    replica_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("replicas.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    counter: Mapped[int] = mapped_column(Integer, nullable=False)
    # Type d'opération : insert, delete
    op_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Position dans le document (index logique avant transformation)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Caractère pour insert, None pour delete
    char: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    # Identifiant de position CRDT (pour ordre total)
    pos_id: Mapped[Optional[List[Any]]] = mapped_column(JSON, nullable=True)
    # Version vector au moment de l'opération
    version_vector: Mapped[Dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    # Timestamp logique
    timestamp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Métadonnées
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
