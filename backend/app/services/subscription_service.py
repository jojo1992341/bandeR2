"""
Service de gestion des abonnements (§9.2, US-053 CDC)

Gère:
- Création et modification des abonnements
- Suivi de la consommation (minutes IA, stockage)
- Vérification des quotas
- Reset de période
- Gestion du dépassement
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Subscription,
    SubscriptionUsage,
    SubscriptionHistory,
    Plan,
    Studio,
)


class SubscriptionService:
    """
    Service de gestion des abonnements (§9.2, US-053).
    
    Responsabilités:
    - Créer/modifier les abonnements
    - Suivre la consommation de façon idempotente
    - Vérifier les quotas
    - Gérer les périodes de facturation
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ============================================================
    # Gestion des abonnements
    # ============================================================
    
    async def get_subscription(self, studio_id: uuid.UUID) -> Optional[Subscription]:
        """Récupère l'abonnement actif d'un studio."""
        result = await self.db.execute(
            select(Subscription)
            .where(
                and_(
                    Subscription.studio_id == studio_id,
                    Subscription.status.in_(["active", "trialing"])
                )
            )
            .order_by(Subscription.billing_period_start.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def create_subscription(
        self,
        studio_id: uuid.UUID,
        plan: str = Plan.FREE,
        billing_period_start: Optional[datetime] = None,
        billing_period_end: Optional[datetime] = None,
    ) -> Subscription:
        """
        Crée un nouvel abonnement pour un studio.
        
        Args:
            studio_id: ID du studio
            plan: Plan souhaité (défaut: free)
            billing_period_start: Début de la période (défaut: maintenant)
            billing_period_end: Fin de la période (défaut: +1 mois)
            
        Returns:
            La subscription créée.
        """
        now = datetime.now(timezone.utc)
        
        if billing_period_start is None:
            billing_period_start = now
        if billing_period_end is None:
            billing_period_end = now + timedelta(days=30)
        
        # Vérifier si un abonnement actif existe
        existing = await self.get_subscription(studio_id)
        if existing:
            # Archiver l'ancien
            existing.status = "cancelled"
            existing.cancelled_at = now
            existing.ends_at = now
            await self._log_history(
                existing.id,
                "plan_changed",
                {
                    "old_plan": existing.plan,
                    "new_plan": plan,
                    "reason": "upgrade_downgrade",
                }
            )
        
        # Créer le nouvel abonnement
        subscription = Subscription(
            studio_id=studio_id,
            plan=plan,
            status="active",
            billing_period_start=billing_period_start,
            billing_period_end=billing_period_end,
            started_at=now,
            amount_before_tax=Plan.PLAN_PRICES.get(plan, 0),
        )
        
        self.db.add(subscription)
        await self.db.flush()
        
        # Créer un historique
        await self._log_history(
            subscription.id,
            "plan_changed",
            {
                "old_plan": existing.plan if existing else None,
                "new_plan": plan,
                "reason": "creation",
            }
        )
        
        # Initialiser l'usage pour la période
        await self._ensure_usage_record(subscription.id, billing_period_start, billing_period_end)
        
        await self.db.commit()
        await self.db.refresh(subscription)
        
        return subscription
    
    async def upgrade_plan(
        self,
        studio_id: uuid.UUID,
        new_plan: str,
    ) -> Subscription:
        """
        Change le plan d'un studio (upgrade ou downgrade).
        
        Args:
            studio_id: ID du studio
            new_plan: Nouveau plan
            
        Returns:
            La subscription mise à jour.
        """
        subscription = await self.get_subscription(studio_id)
        if not subscription:
            raise ValueError(f"Aucun abonnement actif pour le studio {studio_id}")
        
        old_plan = subscription.plan
        
        if old_plan == new_plan:
            return subscription
        
        # Mettre à jour
        subscription.plan = new_plan
        subscription.amount_before_tax = Plan.PLAN_PRICES.get(new_plan, 0)
        
        await self._log_history(
            subscription.id,
            "plan_changed",
            {
                "old_plan": old_plan,
                "new_plan": new_plan,
                "reason": "upgrade" if Plan.PLAN_PRICES.get(new_plan, 0) > Plan.PLAN_PRICES.get(old_plan, 0) else "downgrade",
            }
        )
        
        await self.db.commit()
        await self.db.refresh(subscription)
        
        return subscription
    
    async def cancel_subscription(
        self,
        studio_id: uuid.UUID,
        reason: str = "user_request",
    ) -> Subscription:
        """
        Annule l'abonnement d'un studio.
        
        Args:
            studio_id: ID du studio
            reason: Raison de l'annulation
            
        Returns:
            La subscription annulée.
        """
        subscription = await self.get_subscription(studio_id)
        if not subscription:
            raise ValueError(f"Aucun abonnement actif pour le studio {studio_id}")
        
        subscription.status = "cancelled"
        subscription.cancelled_at = datetime.now(timezone.utc)
        subscription.ends_at = datetime.now(timezone.utc)
        
        await self._log_history(
            subscription.id,
            "cancelled",
            {"reason": reason}
        )
        
        await self.db.commit()
        await self.db.refresh(subscription)
        
        return subscription
    
    # ============================================================
    # Gestion de la consommation
    # ============================================================
    
    async def _ensure_usage_record(
        self,
        subscription_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> SubscriptionUsage:
        """Assure l'existence d'un enregistrement d'usage pour la période."""
        # Vérifier si l'enregistrement existe déjà
        result = await self.db.execute(
            select(SubscriptionUsage).where(
                and_(
                    SubscriptionUsage.subscription_id == subscription_id,
                    SubscriptionUsage.period_start == period_start,
                )
            )
        )
        usage = result.scalar_one_or_none()
        
        if usage:
            return usage
        
        # Créer un nouvel enregistrement
        usage = SubscriptionUsage(
            subscription_id=subscription_id,
            period_start=period_start,
            period_end=period_end,
            ia_minutes_used=0,
            storage_bytes_used=0,
            projects_count=0,
            media_assets_count=0,
            replicas_count=0,
        )
        
        self.db.add(usage)
        await self.db.flush()
        
        return usage
    
    async def increment_usage(
        self,
        studio_id: uuid.UUID,
        ia_minutes: int = 0,
        storage_bytes: int = 0,
        project_created: bool = False,
        media_created: bool = False,
        replica_created: bool = False,
    ) -> Dict[str, Any]:
        """
        Incrémente la consommation de façon idempotente.
        
        ATTENTION: Pour garantir l'idempotence en production,
        cette méthode doit être appelée dans une transaction avec
        une vérification optimiste (version) ou un lock.
        
        Args:
            studio_id: ID du studio
            ia_minutes: Minutes IA à ajouter
            storage_bytes: Octets de stockage à ajouter
            project_created: True si un projet a été créé
            media_created: True si un média a été créé
            replica_created: True si une réplique a été créée
            
        Returns:
            Dict avec l'état de la consommation et éventuellement des warnings.
        """
        subscription = await self.get_subscription(studio_id)
        if not subscription:
            raise ValueError(f"Aucun abonnement actif pour le studio {studio_id}")
        
        now = datetime.now(timezone.utc)
        period_start = subscription.billing_period_start
        period_end = subscription.billing_period_end
        
        # S'assurer que l'enregistrement d'usage existe
        usage = await self._ensure_usage_record(
            subscription.id, period_start, period_end
        )
        
        # Récupérer les quotas du plan
        quotas = Plan.PLANS.get(subscription.plan, Plan.FREE_QUOTAS)
        
        # Vérifier les limites avant d'incrémenter
        warnings = []
        overages = {}
        
        # Minutes IA
        if ia_minutes > 0:
            if quotas.get("max_minutes_ia_per_month", 0) > 0:
                new_minutes = usage.ia_minutes_used + ia_minutes
                max_minutes = quotas["max_minutes_ia_per_month"]
                
                if new_minutes > max_minutes:
                    overage = new_minutes - max_minutes
                    if subscription.overage_behavior == "block":
                        raise QuotaExceededError(
                            f"Quota minutes IA dépassé: {new_minutes}/{max_minutes}",
                            plan=subscription.plan,
                            used=new_minutes,
                            limit=max_minutes,
                        )
                    else:
                        overages["ia_minutes"] = overage
                        warnings.append(f"Dépassement minutes IA: +{overage}")
        
        # Stockage
        if storage_bytes > 0:
            if quotas.get("max_storage_gb", 0) > 0:
                max_storage = quotas["max_storage_gb"] * 1024 * 1024 * 1024  # GB → bytes
                new_storage = usage.storage_bytes_used + storage_bytes
                
                if new_storage > max_storage:
                    overage = new_storage - max_storage
                    if subscription.overage_behavior == "block":
                        raise QuotaExceededError(
                            f"Quota stockage dépassé: {new_storage}/{max_storage} bytes",
                            plan=subscription.plan,
                            used=new_storage,
                            limit=max_storage,
                        )
                    else:
                        overages["storage"] = overage
                        warnings.append(f"Dépassement stockage: +{overage} bytes")
        
        # Projets
        if project_created:
            if quotas.get("max_projects", 0) > 0:
                new_projects = usage.projects_count + 1
                max_projects = quotas["max_projects"]
                
                if new_projects > max_projects and max_projects > 0:
                    overage = new_projects - max_projects
                    overages["projects"] = overage
                    warnings.append(f"Dépassement projets: +{overage}")
        
        # Médias
        if media_created:
            if quotas.get("max_media_assets", 0) > 0:
                new_media = usage.media_assets_count + 1
                max_media = quotas["max_media_assets"]
                
                if new_media > max_media and max_media > 0:
                    overage = new_media - max_media
                    overages["media"] = overage
                    warnings.append(f"Dépassement médias: +{overage}")
        
        # Répliques
        if replica_created:
            if quotas.get("max_replicas", 0) > 0:
                new_replicas = usage.replicas_count + 1
                max_replicas = quotas["max_replicas"]
                
                if new_replicas > max_replicas and max_replicas > 0:
                    overage = new_replicas - max_replicas
                    overages["replicas"] = overage
                    warnings.append(f"Dépassement répliques: +{overage}")
        
        # Incrémenter les compteurs (dans la mesure du possible)
        if ia_minutes > 0:
            usage.ia_minutes_used += ia_minutes
        if storage_bytes > 0:
            usage.storage_bytes_used += storage_bytes
        if project_created:
            usage.projects_count += 1
        if media_created:
            usage.media_assets_count += 1
        if replica_created:
            usage.replicas_count += 1
        
        # Enregistrer les dépassements
        for key, value in overages.items():
            if key == "ia_minutes":
                usage.overage_minutes += value
            elif key == "storage":
                usage.overage_storage_bytes += value
            elif key == "projects":
                usage.overage_projects += value
            elif key == "replicas":
                usage.overage_replicas += value
        
        # Logguer l'historique si dépassement
        if overages:
            await self._log_history(
                subscription.id,
                "overage_warning",
                {
                    "overages": overages,
                    "warnings": warnings,
                }
            )
        
        await self.db.flush()
        
        return {
            "success": True,
            "warnings": warnings,
            "overages": overages,
            "current_usage": {
                "ia_minutes_used": usage.ia_minutes_used,
                "storage_bytes_used": usage.storage_bytes_used,
                "projects_count": usage.projects_count,
                "media_assets_count": usage.media_assets_count,
                "replicas_count": usage.replicas_count,
            },
        }
    
    async def get_usage_summary(self, studio_id: uuid.UUID) -> Dict[str, Any]:
        """
        Récupère le résumé de la consommation actuelle.
        
        Returns:
            Dict avec la consommation actuelle et les limites du plan.
        """
        subscription = await self.get_subscription(studio_id)
        if not subscription:
            return {"error": "Aucun abonnement actif"}
        
        quotas = Plan.PLANS.get(subscription.plan, Plan.FREE_QUOTAS)
        
        # Trouver l'usage de la période en cours
        result = await self.db.execute(
            select(SubscriptionUsage).where(
                and_(
                    SubscriptionUsage.subscription_id == subscription.id,
                    SubscriptionUsage.period_start == subscription.billing_period_start,
                )
            )
        )
        usage = result.scalar_one_or_none()
        
        if not usage:
            usage_data = {
                "ia_minutes_used": 0,
                "storage_bytes_used": 0,
                "projects_count": 0,
                "media_assets_count": 0,
                "replicas_count": 0,
            }
        else:
            usage_data = {
                "ia_minutes_used": usage.ia_minutes_used,
                "storage_bytes_used": usage.storage_bytes_used,
                "projects_count": usage.projects_count,
                "media_assets_count": usage.media_assets_count,
                "replicas_count": usage.replicas_count,
            }
        
        # Calculer les limites
        max_minutes = quotas.get("max_minutes_ia_per_month", 0)
        max_storage_gb = quotas.get("max_storage_gb", 0)
        max_projects = quotas.get("max_projects", 0)
        max_media = quotas.get("max_media_assets", 0)
        max_replicas = quotas.get("max_replicas", 0)
        
        return {
            "studio_id": str(studio_id),
            "plan": subscription.plan,
            "status": subscription.status,
            "billing_period": {
                "start": subscription.billing_period_start.isoformat(),
                "end": subscription.billing_period_end.isoformat(),
            },
            "quotas": {
                "max_minutes_ia_per_month": max_minutes if max_minutes > 0 else "illimité",
                "max_storage_gb": max_storage_gb if max_storage_gb > 0 else "illimité",
                "max_projects": max_projects if max_projects > 0 else "illimité",
                "max_media_assets": max_media if max_media > 0 else "illimité",
                "max_replicas": max_replicas if max_replicas > 0 else "illimité",
            },
            "usage": usage_data,
            "usage_percent": {
                "ia_minutes": (
                    (usage_data["ia_minutes_used"] / max_minutes * 100)
                    if max_minutes > 0 else 0
                ),
                "storage": (
                    (usage_data["storage_bytes_used"] / (max_storage_gb * 1024**3) * 100)
                    if max_storage_gb > 0 else 0
                ),
                "projects": (
                    (usage_data["projects_count"] / max_projects * 100)
                    if max_projects > 0 else 0
                ),
                "media": (
                    (usage_data["media_assets_count"] / max_media * 100)
                    if max_media > 0 else 0
                ),
                "replicas": (
                    (usage_data["replicas_count"] / max_replicas * 100)
                    if max_replicas > 0 else 0
                ),
            },
            "overages": {
                "minutes": usage.overage_minutes if usage else 0,
                "storage": usage.overage_storage_bytes if usage else 0,
                "projects": usage.overage_projects if usage else 0,
                "replicas": usage.overage_replicas if usage else 0,
            },
        }
    
    async def reset_period(self, studio_id: uuid.UUID) -> SubscriptionUsage:
        """
        Réinitialise la période de facturation (remise à zéro des compteurs).
        
        Args:
            studio_id: ID du studio
            
        Returns:
            Le nouvel enregistrement d'usage.
        """
        subscription = await self.get_subscription(studio_id)
        if not subscription:
            raise ValueError(f"Aucun abonnement actif pour le studio {studio_id}")
        
        now = datetime.now(timezone.utc)
        new_period_start = now
        new_period_end = now + timedelta(days=30)
        
        # Mettre à jour la période
        subscription.billing_period_start = new_period_start
        subscription.billing_period_end = new_period_end
        
        # Créer un nouvel historique
        await self._log_history(
            subscription.id,
            "period_reset",
            {
                "old_period_start": subscription.billing_period_start.isoformat(),
                "old_period_end": subscription.billing_period_end.isoformat(),
                "new_period_start": new_period_start.isoformat(),
                "new_period_end": new_period_end.isoformat(),
            }
        )
        
        # Créer un nouvel usage
        usage = SubscriptionUsage(
            subscription_id=subscription.id,
            period_start=new_period_start,
            period_end=new_period_end,
        )
        
        self.db.add(usage)
        await self.db.commit()
        await self.db.refresh(usage)
        
        return usage
    
    async def _log_history(
        self,
        subscription_id: uuid.UUID,
        event_type: str,
        event_data: Dict[str, Any],
        created_by: Optional[str] = "system",
    ) -> SubscriptionHistory:
        """Crée un enregistrement d'historique."""
        history = SubscriptionHistory(
            subscription_id=subscription_id,
            event_type=event_type,
            event_data=event_data,
            created_by=created_by,
        )
        self.db.add(history)
        await self.db.flush()
        return history


# ============================================================
# Exceptions
# ============================================================
class QuotaExceededError(Exception):
    """Levée lorsque le quota d'un abonnement est dépassé."""
    
    def __init__(self, message: str, plan: str = "", used: Any = 0, limit: Any = 0):
        super().__init__(message)
        self.plan = plan
        self.used = used
        self.limit = limit
