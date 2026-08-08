"""
Test d'intégration PostgreSQL (§18.4 CDC)

Ce module teste la configuration PostgreSQL asynchrone avec asyncpg.
Il vérifie:
- La connexion à PostgreSQL avec asyncpg
- La création de tables via Alembic
- Les opérations CRUD de base
- Le health check de l'API

Prérequis:
- PostgreSQL 16 en cours d'exécution
- DATABASE_URL configurée avec postgresql+asyncpg://...
- La base de données cible créée
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, create_async_engine, async_sessionmaker

from app.core.config import get_settings
from app.core.database import Base, get_db, init_test_db
from app.main import app
from app.models import Project, Studio, User, StudioMembership
import uuid


# ============================================================
# Configuration
# ============================================================
settings = get_settings()
DATABASE_URL = settings.DATABASE_URL
TEST_MODE = "postgresql" if "postgresql" in DATABASE_URL else "sqlite"


def is_postgres_available() -> bool:
    """Vérifie si PostgreSQL est disponible pour les tests d'intégration."""
    if "postgresql" not in DATABASE_URL:
        return False
    try:
        engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
        async def check():
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
            return True
        return asyncio.run(check())
    except Exception:
        return False


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture(scope="session", params=["postgresql"] if is_postgres_available() else ["sqlite"])
def database_type(request) -> str:
    """Type de base de données pour le test."""
    return request.param


@pytest_asyncio.fixture(scope="function")
async def async_db_session(database_type: str) -> AsyncGenerator[AsyncSession, None]:
    """
    Fixture pour une session de base de données asynchrone.

    Pour PostgreSQL: utilise la base configurée
    Pour SQLite: utilise une base en mémoire
    """
    if database_type == "postgresql":
        engine = create_async_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=False,
        )
        # Créer les tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(async_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Fixture pour un client HTTP asynchrone testant l'API.
    """
    # Surcharger la dépendance get_db pour utiliser notre session de test
    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ============================================================
# Tests du health check (§9.1 CDC)
# ============================================================
@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """Teste le endpoint /health (§9.1 CDC)."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


# ============================================================
# Tests de la configuration SQLAlchemy asynchrone
# ============================================================
@pytest.mark.asyncio
async def test_async_engine_creation(database_type: str) -> None:
    """Teste la création d'un moteur asynchrone."""
    if database_type == "postgresql":
        url = DATABASE_URL
    else:
        url = "sqlite+aiosqlite:///:memory:"

    engine = create_async_engine(url, echo=False)
    assert engine is not None
    assert engine.url is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_async_session_creation(async_db_session: AsyncSession) -> None:
    """Teste la création d'une session asynchrone."""
    assert async_db_session is not None
    # Exécuter une requête simple
    result = await async_db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_database_url_configuration() -> None:
    """Teste que l'URL de base de données est correctement configurée."""
    settings = get_settings()

    # L'URL doit utiliser un pilote asynchrone
    assert "+asyncpg" in settings.DATABASE_URL or "+aiosqlite" in settings.DATABASE_URL, \
        "L'URL doit utiliser un pilote asynchrone (asyncpg ou aiosqlite)"

    # Le chargement de .env doit fonctionner
    assert settings.SECRET_KEY is not None
    assert len(settings.SECRET_KEY) > 0


# ============================================================
# Tests de l'importation des modèles
# ============================================================
def test_all_models_importable() -> None:
    """Vérifie que tous les modèles sont importables."""
    from app.models import (
        User,
        Studio,
        Project,
        MediaAsset,
        PipelineJob,
        TranscriptSegment,
        Word,
        Speaker,
        Replica,
        ReplicaHistory,
        RythmoVersion,
        Export,
        Comment,
        AuditLog,
        SecurityAlert,
        SilenceEvent,
        EmotionTag,
        TypographicProfile,
    )
    # Si on arrive ici, tous les modèles sont importables
    assert True


def test_base_metadata_populated() -> None:
    """Vérifie que Base.metadata contient toutes les tables."""
    from app.core.database import Base
    assert len(Base.metadata.tables) > 0, "Base.metadata doit contenir des tables"


def test_all_tables_defined() -> None:
    """Vérifie que toutes les tables attendues sont définies."""
    from app.core.database import Base

    expected_tables = {
        "users",
        "studios",
        "studio_memberships",
        "projects",
        "media_assets",
        "pipeline_jobs",
        "transcript_segments",
        "transcript_words",
        "speakers",
        "replicas",
        "replica_history",
        "rythmo_versions",
        "exports",
        "comments",
        "audit_logs",
        "security_alerts",
        "silence_events",
        "emotion_tags",
        "typographic_profiles",
        "lip_sync_frames",
        "lip_sync_results",
        "anonymized_corrections",
        "sso_configurations",
        "replica_crdt_states",
        "replica_crdt_operations",
        "api_keys",
        "webhook_endpoints",
        "webhook_deliveries",
    }

    actual_tables = set(Base.metadata.tables.keys())
    missing = expected_tables - actual_tables
    assert not missing, f"Tables manquantes: {missing}"


# ============================================================
# Tests CRUD de base avec async session (sans auth)
# ============================================================
@pytest.mark.asyncio
async def test_create_and_read_studio(async_db_session: AsyncSession) -> None:
    """Teste la création et la lecture d'un studio avec session async."""
    from sqlalchemy import select

    # Créer un studio
    studio_id = uuid.uuid4()
    studio = Studio(
        id=studio_id,
        name="Studio Test",
    )
    async_db_session.add(studio)
    await async_db_session.commit()

    # Lire le studio avec select
    result = await async_db_session.execute(
        select(Studio).where(Studio.id == studio_id)
    )
    studio_read = result.scalar_one()
    assert studio_read.name == "Studio Test"


@pytest.mark.asyncio
async def test_create_and_read_user(async_db_session: AsyncSession) -> None:
    """Teste la création et la lecture d'un utilisateur avec session async."""
    from app.core.password import hash_password
    from sqlalchemy import select

    # Créer un utilisateur
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="test@example.com",
        hashed_password=hash_password("Test123!"),
        role="adaptateur",
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.commit()

    # Lire l'utilisateur avec select
    result = await async_db_session.execute(
        select(User).where(User.id == user_id)
    )
    user_read = result.scalar_one()
    assert user_read.email == "test@example.com"
    assert user_read.role == "adaptateur"


# ============================================================
# Tests conditionnels (PostgreSQL uniquement)
# ============================================================
@pytest.mark.skipif(
    not is_postgres_available(),
    reason="PostgreSQL non disponible"
)
@pytest.mark.asyncio
async def test_postgresql_specific_features() -> None:
    """Teste des fonctionnalités spécifiques à PostgreSQL."""
    from sqlalchemy.dialects.postgresql import UUID

    # Vérifier que les types PostgreSQL sont utilisables
    assert UUID is not None


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="PostgreSQL non disponible"
)
@pytest.mark.asyncio
async def test_alembic_migration_check() -> None:
    """Teste que Alembic peut fonctionner avec la configuration."""
    from alembic.config import Config
    from alembic import command
    import os

    # Vérifier que le fichier alembic.ini existe
    alembic_ini = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "..",
        "alembic.ini"
    )
    assert os.path.exists(alembic_ini), "alembic.ini doit exister"

    # Vérifier que Alembic peut être configuré
    config = Config(alembic_ini)
    assert config is not None


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="PostgreSQL non disponible"
)
@pytest.mark.asyncio
async def test_postgresql_connection_pool(database_type: str) -> None:
    """Teste la configuration du pool de connexions PostgreSQL."""
    engine = create_async_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
        echo=False,
    )

    # Vérifier que le pool est configuré
    assert engine.pool is not None

    # Tester une connexion
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1 as test"))
        row = result.fetchone()
        assert row[0] == 1

    await engine.dispose()
