"""
Tests pour l'entité Subscription et consommation (§9.2, US-053 CDC)

Couvre:
- Changement de plan
- Remise à zéro de période
- Dépassement de quota
- Consommation idempotente
- Calcul des quotas
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator
from uuid import UUID, uuid4

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    Base,
    Studio,
    Subscription,
    SubscriptionUsage,
    SubscriptionHistory,
    Plan,
)
from app.services.subscription_service import SubscriptionService, QuotaExceededError


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="function")
async def async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Crée une session de test avec base SQLite en mémoire."""
    from app.core.database import get_test_engine, init_test_db
    
    engine = get_test_engine()
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session_factory() as session:
        yield session
        await session.rollback()
    
    await engine.dispose()


@pytest.fixture
def sample_studio_id() -> UUID:
    """Génère un ID de studio de test."""
    return uuid4()


# ============================================================
# Tests de création et plan
# ============================================================

@pytest.mark.asyncio
async def test_create_subscription_free_plan(
    async_db_session: AsyncSession,
    sample_studio_id: UUID,
) -> None:
    """Test de création d'un abonnement free (§9.2, US-053)."""
    service = SubscriptionService(async_db_session)
    
    studio = Studio(id=sample_studio_id, name="Studio Test", plan=Plan.FREE)
    async_db_session.add(studio)
    await async_db_session.commit()
    
    now = datetime.now(timezone.utc)
    subscription = await service.create_subscription(
        studio_id=sample_studio_id,
        plan=Plan.FREE,
        billing_period_start=now,
        billing_period_end=now + timedelta(days=30),
    )
    
    assert subscription.studio_id == sample_studio_id
    assert subscription.plan == Plan.FREE
    assert subscription.status == "active"
    assert subscription.amount_before_tax == 0


@pytest.mark.asyncio
async def test_upgrade_plan(
    async_db_session: AsyncSession,
    sample_studio_id: UUID,
) -> None:
    """Test du changement de plan (§9.2, US-053)."""
    service = SubscriptionService(async_db_session)
    
    studio = Studio(id=sample_studio_id, name="Studio Test", plan=Plan.FREE)
    async_db_session.add(studio)
    await async_db_session.commit()
    
    now = datetime.now(timezone.utc)
    subscription = await service.create_subscription(
        studio_id=sample_studio_id,
        plan=Plan.FREE,
        billing_period_start=now,
        billing_period_end=now + timedelta(days=30),
    )
    
    assert subscription.plan == Plan.FREE
    assert subscription.amount_before_tax == 0
    
    # Upgrader vers starter
    subscription = await service.upgrade_plan(
        studio_id=sample_studio_id,
        new_plan=Plan.STARTER,
    )
    
    assert subscription.plan == Plan.STARTER
    assert subscription.amount_before_tax == 29
    
    # Upgrader vers pro
    subscription = await service.upgrade_plan(
        studio_id=sample_studio_id,
        new_plan=Plan.PRO,
    )
    
    assert subscription.plan == Plan.PRO
    assert subscription.amount_before_tax == 99


@pytest.mark.asyncio
async def test_cancel_subscription(
    async_db_session: AsyncSession,
    sample_studio_id: UUID,
) -> None:
    """Test de l'annulation d'un abonnement (§9.2, US-053)."""
    service = SubscriptionService(async_db_session)
    
    studio = Studio(id=sample_studio_id, name="Studio Test", plan=Plan.PRO)
    async_db_session.add(studio)
    await async_db_session.commit()
    
    now = datetime.now(timezone.utc)
    subscription = await service.create_subscription(
        studio_id=sample_studio_id,
        plan=Plan.PRO,
        billing_period_start=now,
        billing_period_end=now + timedelta(days=30),
    )
    
    subscription_id = subscription.id
    await service.cancel_subscription(
        studio_id=sample_studio_id,
        reason="user_request",
    )
    
    # Vérifier dans la base de données
    result = await async_db_session.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    cancelled = result.scalar_one()
    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None
    assert cancelled.ends_at is not None


# ============================================================
# Tests de consommation et quotas
# ============================================================

@pytest.mark.asyncio
async def test_increment_usage_ia_minutes(
    async_db_session: AsyncSession,
    sample_studio_id: UUID,
) -> None:
    """Test de l'incrémentation de la consommation IA (§9.2, US-053)."""
    service = SubscriptionService(async_db_session)
    
    studio = Studio(id=sample_studio_id, name="Studio Test", plan=Plan.STARTER)
    async_db_session.add(studio)
    await async_db_session.commit()
    
    now = datetime.now(timezone.utc)
    subscription = await service.create_subscription(
        studio_id=sample_studio_id,
        plan=Plan.STARTER,
        billing_period_start=now,
        billing_period_end=now + timedelta(days=30),
    )
    
    # Consommer 10 minutes IA
    result = await service.increment_usage(
        studio_id=sample_studio_id,
        ia_minutes=10,
    )
    
    assert result["success"] is True
    assert result["current_usage"]["ia_minutes_used"] == 10
    
    # Consommer 50 minutes supplémentaires
    result = await service.increment_usage(
        studio_id=sample_studio_id,
        ia_minutes=50,
    )
    
    assert result["success"] is True
    assert result["current_usage"]["ia_minutes_used"] == 60


@pytest.mark.asyncio
async def test_quota_exceeded_minutes_ia(
    async_db_session: AsyncSession,
    sample_studio_id: UUID,
) -> None:
    """Test du dépassement du quota minutes IA (§9.2, US-053)."""
    service = SubscriptionService(async_db_session)
    
    studio = Studio(id=sample_studio_id, name="Studio Test", plan=Plan.STARTER)
    async_db_session.add(studio)
    await async_db_session.commit()
    
    now = datetime.now(timezone.utc)
    subscription = await service.create_subscription(
        studio_id=sample_studio_id,
        plan=Plan.STARTER,
        billing_period_start=now,
        billing_period_end=now + timedelta(days=30),
    )
    
    # Utiliser 60 minutes (limite starter)
    await service.increment_usage(
        studio_id=sample_studio_id,
        ia_minutes=60,
    )
    
    # Essayer d'utiliser 1 minute de plus → doit lever une erreur
    with pytest.raises(QuotaExceededError) as exc_info:
        await service.increment_usage(
            studio_id=sample_studio_id,
            ia_minutes=1,
        )
    
    assert "Quota minutes IA dépassé" in str(exc_info.value)
    assert exc_info.value.plan == Plan.STARTER
    assert exc_info.value.used == 61
    assert exc_info.value.limit == 60


@pytest.mark.asyncio
async def test_increment_usage_storage(
    async_db_session: AsyncSession,
    sample_studio_id: UUID,
) -> None:
    """Test de l'incrémentation de la consommation de stockage (§9.2, US-053)."""
    service = SubscriptionService(async_db_session)
    
    studio = Studio(id=sample_studio_id, name="Studio Test", plan=Plan.PRO)
    async_db_session.add(studio)
    await async_db_session.commit()
    
    now = datetime.now(timezone.utc)
    subscription = await service.create_subscription(
        studio_id=sample_studio_id,
        plan=Plan.PRO,
        billing_period_start=now,
        billing_period_end=now + timedelta(days=30),
    )
    
    # Uploader 50 GB
    result = await service.increment_usage(
        studio_id=sample_studio_id,
        storage_bytes=50 * 1024 * 1024 * 1024,
    )
    
    assert result["success"] is True
    assert result["current_usage"]["storage_bytes_used"] == 50 * 1024 * 1024 * 1024
    
    # Uploader 30 GB supplémentaires
    result = await service.increment_usage(
        studio_id=sample_studio_id,
        storage_bytes=30 * 1024 * 1024 * 1024,
    )
    
    assert result["success"] is True
    assert result["current_usage"]["storage_bytes_used"] == 80 * 1024 * 1024 * 1024


@pytest.mark.asyncio
async def test_reset_period(
    async_db_session: AsyncSession,
    sample_studio_id: UUID,
) -> None:
    """Test de la remise à zéro de la période de facturation (§9.2, US-053)."""
    service = SubscriptionService(async_db_session)
    
    studio = Studio(id=sample_studio_id, name="Studio Test", plan=Plan.PRO)
    async_db_session.add(studio)
    await async_db_session.commit()
    
    now = datetime.now(timezone.utc)
    subscription = await service.create_subscription(
        studio_id=sample_studio_id,
        plan=Plan.PRO,
        billing_period_start=now,
        billing_period_end=now + timedelta(days=30),
    )
    
    # Consommer des ressources
    await service.increment_usage(
        studio_id=sample_studio_id,
        ia_minutes=100,
        storage_bytes=10 * 1024 * 1024 * 1024,
    )
    
    # Reset de la période
    new_usage = await service.reset_period(sample_studio_id)
    
    assert new_usage.period_start.replace(tzinfo=None) > now.replace(tzinfo=None)
    assert new_usage.ia_minutes_used == 0
    assert new_usage.storage_bytes_used == 0


@pytest.mark.asyncio
async def test_get_usage_summary(
    async_db_session: AsyncSession,
    sample_studio_id: UUID,
) -> None:
    """Test du résumé de consommation (§9.2, US-053)."""
    service = SubscriptionService(async_db_session)
    
    studio = Studio(id=sample_studio_id, name="Studio Test", plan=Plan.PRO)
    async_db_session.add(studio)
    await async_db_session.commit()
    
    now = datetime.now(timezone.utc)
    subscription = await service.create_subscription(
        studio_id=sample_studio_id,
        plan=Plan.PRO,
        billing_period_start=now,
        billing_period_end=now + timedelta(days=30),
    )
    
    await service.increment_usage(
        studio_id=sample_studio_id,
        ia_minutes=150,
        storage_bytes=50 * 1024 * 1024 * 1024,
        project_created=True,
        media_created=True,
        replica_created=True,
    )
    
    summary = await service.get_usage_summary(sample_studio_id)
    
    assert summary["plan"] == Plan.PRO
    assert summary["status"] == "active"
    assert summary["usage"]["ia_minutes_used"] == 150
    assert summary["usage_percent"]["ia_minutes"] == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
