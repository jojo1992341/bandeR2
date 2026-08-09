"""
Entité Subscription (§9.2, US-053 CDC)

Gestion des abonnements, plans, périodes de facturation et consommation
réelle des ressources (minutes IA, stockage).

Modèle:
- Plan: définition des plans disponibles (free, starter, pro, enterprise)
- Subscription: abonnement actif d'un studio
- SubscriptionUsage: compteurs de consommation (idempotence garantie)
- SubscriptionHistory: historique des changements (audit trail)
"""

from __future__ import annotations

import uuid
from app.core.uuid7 import uuid7
from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    Numeric,
    BigInteger,
    ForeignKey,
    Text,
    Boolean,
    JSON,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


# ============================================================
# Plans disponibles
# ============================================================
class Plan:
    """Définition des plans disponibles (US-053)."""
    
    # Plan Free
    FREE = "free"
    FREE_QUOTAS = {
        "max_minutes_ia_per_month": 10,        # 10 minutes IA/mois
        "max_storage_gb": 1,                    # 1 GB stockage
        "max_projects": 1,                      # 1 projet
        "max_media_assets": 5,                  # 5 médias
        "max_replicas": 100,                    # 100 répliques
        "exports_allowed": False,               # Pas d'export
        "priority_support": False,
        "s3_bucket": "rythmoai-free",
    }
    
    # Plan Starter
    STARTER = "starter"
    STARTER_QUOTAS = {
        "max_minutes_ia_per_month": 60,        # 1 heure IA/mois
        "max_storage_gb": 10,                   # 10 GB stockage
        "max_projects": 5,                      # 5 projets
        "max_media_assets": 50,                 # 50 médias
        "max_replicas": 5000,                   # 5000 répliques
        "exports_allowed": True,
        "export_formats": ["srt", "vtt"],
        "priority_support": False,
        "s3_bucket": "rythmoai-starter",
    }
    
    # Plan Pro
    PRO = "pro"
    PRO_QUOTAS = {
        "max_minutes_ia_per_month": 300,       # 5 heures IA/mois
        "max_storage_gb": 100,                  # 100 GB stockage
        "max_projects": 20,                     # 20 projets
        "max_media_assets": 500,                # 500 médias
        "max_replicas": 50000,                  # 50000 répliques
        "exports_allowed": True,
        "export_formats": ["srt", "vtt", "stl", "pdf"],
        "priority_support": True,
        "s3_bucket": "rythmoai-pro",
        "watermark_disabled": False,
    }
    
    # Plan Enterprise
    ENTERPRISE = "enterprise"
    ENTERPRISE_QUOTAS = {
        "max_minutes_ia_per_month": -1,        # Illimité
        "max_storage_gb": -1,                   # Illimité
        "max_projects": -1,                     # Illimité
        "max_media_assets": -1,
        "max_replicas": -1,
        "exports_allowed": True,
        "export_formats": ["srt", "vtt", "stl", "pdf", "cavena"],
        "priority_support": True,
        "s3_bucket": "rythmoai-enterprise",
        "watermark_disabled": True,
        "custom_sla": True,
    }
    
    PLANS = {
        FREE: FREE_QUOTAS,
        STARTER: STARTER_QUOTAS,
        PRO: PRO_QUOTAS,
        ENTERPRISE: ENTERPRISE_QUOTAS,
    }
    
    PLAN_PRICES = {  # Prix mensuels en EUR
        FREE: 0,
        STARTER: 29,
        PRO: 99,
        ENTERPRISE: 299,
    }


# ============================================================
# Entité Subscription (abonnement actif)
# ============================================================
class Subscription(Base):
    """
    Abonnement d'un studio (§9.2, US-053).
    
    Représente l'abonnement actif d'un studio avec:
    - Plan actuel
    - Période de facturation (mensuelle)
    - Date de début/fin
    - Statut (active, past_due, cancelled, expired)
    """
    __tablename__ = "subscriptions"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    studio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("studios.id"), nullable=False, index=True
    )
    plan: Mapped[str] = mapped_column(
        String(50), nullable=False, default=Plan.FREE, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", index=True
    )  # active, past_due, cancelled, expired, trialing
    
    # Période de facturation (mensuelle)
    billing_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    billing_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    
    # Dates d'abonnement
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    
    # Facturation
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    amount_before_tax: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0
    )
    tax_rate: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.20  # 20% TVA par défaut
    )
    
    # Courtier (pour le dépassement)
    overage_behavior: Mapped[str] = mapped_column(
        String(50), nullable=False, default="block"  # block, warn, allow
    )
    
    # Métadonnées
    subscription_metadata: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        default=dict
    )
    
    # Relations
    studio: Mapped["Studio"] = relationship("Studio", back_populates="subscription")
    usages: Mapped[List["SubscriptionUsage"]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    history: Mapped[List["SubscriptionHistory"]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("studio_id", "status", name="uq_studio_active_subscription"),
        Index("ix_subscription_billing_period", "billing_period_start", "billing_period_end"),
    )


# ============================================================
# Entité SubscriptionUsage (compteurs de consommation)
# ============================================================
class SubscriptionUsage(Base):
    """
    Compteurs de consommation d'un abonnement (§9.2, US-053).
    
    Tracke la consommation réelle des ressources:
    - Minutes IA utilisées pendant la période
    - Stockage utilisé
    - Nombre de projets, médias, répliques
    
    L'implémentation doit garantir l'idempotence des incréments.
    """
    __tablename__ = "subscription_usages"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=False, index=True
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    
    # Compteurs de consommation
    ia_minutes_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )
    storage_bytes_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    projects_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    media_assets_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    replicas_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    
    # État du cycle de facturation
    is_billed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    billed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    
    # Dépassements éventuels
    overage_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    overage_storage_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    overage_projects: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    overage_replicas: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    
    # Timestamp de dernière mise à jour (pour détection de concurrence)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    
    # Relations
    subscription: Mapped["Subscription"] = relationship(back_populates="usages")

    __table_args__ = (
        Index(
            "ix_subscription_usage_period",
            "subscription_id",
            "period_start",
            unique=True
        ),
    )


# ============================================================
# Entité SubscriptionHistory (audit trail)
# ============================================================
class SubscriptionHistory(Base):
    """
    Historique des changements d'abonnement (§9.2, US-053).
    
    Garde une trace de tous les changements pour audit et facturation.
    """
    __tablename__ = "subscription_history"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # plan_changed, period_reset, overage_warning, billed, cancelled, etc.
    
    event_data: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    # Exemple: {"old_plan": "free", "new_plan": "starter", "effective_date": "..."}
    
    created_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # user_id, system, stripe_webhook, etc.
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    
    # Relations
    subscription: Mapped["Subscription"] = relationship(back_populates="history")
