"""
Configuration pytest pour les tests (§18.4 CDC)

Fournit:
- Fixtures pour les sessions de base de données asynchrones
- Configuration pour les tests unitaires (SQLite) et d'intégration (PostgreSQL)
"""

from __future__ import annotations

import asyncio
import os

# ---------------------------------------------------------------------------
# Harnais de test : forcer SQLite en l'absence de base explicite.
# La CI ne fournit pas de service PostgreSQL ; par défaut l'URL construite
# pointerait vers un PostgreSQL injoignable. On utilise donc une base SQLite
# partagée en mémoire pour toute la session de test. Si DATABASE_URL est
# explicitement positionnée (ex. Postgres pour tests d'intégration), elle est
# respectée.
# ---------------------------------------------------------------------------
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
# Invalider un éventuel cache de settings chargé avant ce point.
try:
    from app.core.config import get_settings as _get_settings  # noqa: F401

    _get_settings.cache_clear()
except Exception:  # pragma: no cover - app pas encore importée
    pass

from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker as sync_sessionmaker

from app.core.config import get_settings, Settings
from app.core.database import (
    Base,
    close_engine,
    close_test_engine,
    dispose_all,
    get_async_session_factory,
    get_test_engine,
    init_test_db,
)
from app.main import app


# ============================================================
# Configuration des tests
# ============================================================
def pytest_configure(config):
    """Configuration initiale de pytest."""
    # Déterminer le mode de test
    config.option.test_mode = os.getenv("TEST_MODE", "unit")  # unit ou integration


# ============================================================
# Fixtures pour la configuration
# ============================================================
@pytest.fixture(scope="session")
def settings() -> Settings:
    """Retourne la configuration pour les tests."""
    return get_settings()


@pytest.fixture(scope="session")
def test_mode(settings: Settings) -> str:
    """Retourne le mode de test (unit ou integration)."""
    db_url = settings.DATABASE_URL
    if "postgresql" in db_url:
        return "integration"
    return "unit"


# ============================================================
# Fixtures pour les tests unitaires (SQLite asynchrone)
# ============================================================
@pytest_asyncio.fixture(scope="function")
async def async_test_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Fixture pour une session de base de données de test asynchrone (SQLite).

    Crée une base de données SQLite en mémoire fraîche pour chaque test.
    """
    # Créer un moteur frais pour ce test
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Créer les tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Créer une session
    async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session_factory() as session:
        yield session

    # Nettoyer
    await engine.dispose()


@pytest.fixture(scope="function")
def test_db_sync(async_test_db: AsyncSession) -> Generator:
    """
    Fixture synchrone pour compatibilité avec les tests existants.
    Utilise une session asynchrone mais retourne un contexte de test.
    """
    # Cette fixture est une passerelle pour les tests qui ont besoin
    # d'une interface synchrone pour SQLite
    yield {
        "engine": async_test_db.bind if async_test_db.bind else None,
        "session": async_test_db,
    }


# ============================================================
# Fixtures pour l'application Flask/FastAPI
# ============================================================
@pytest.fixture(scope="function")
def client(async_test_db: AsyncSession) -> Generator[TestClient, None, None]:
    """
    Fixture pour créer un client de test FastAPI avec une session de base de données.

    Note: Cette fixture utilise le TestClient synchrone de FastAPI.
    Pour les tests asynchrones complets, utilisez directement httpx.AsyncClient.
    """
    # S'assurer que l'application utilise la bonne session de test
    # Pour les tests asynchrones complets, utiliser @pytest.mark.asyncio
    with TestClient(app) as test_client:
        yield test_client


# ============================================================
# Fixtures pour les tests d'intégration PostgreSQL
# ============================================================
@pytest_asyncio.fixture(scope="session")
async def async_pg_engine(settings: Settings) -> AsyncGenerator:
    """
    Fixture pour le moteur PostgreSQL de test (intégration).

    Nécessite que DATABASE_URL pointe vers une base PostgreSQL accessible.
    """
    # Vérifier que nous utilisons bien PostgreSQL
    db_url = settings.DATABASE_URL
    if "postgresql" not in db_url:
        pytest.skip("PostgreSQL non configuré pour les tests d'intégration")

    engine = create_async_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=False,
    )

    # Créer les tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Nettoyer
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def async_pg_session(async_pg_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Fixture pour une session PostgreSQL de test.
    """
    async_session_factory = async_sessionmaker(
        bind=async_pg_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session_factory() as session:
        yield session
        await session.rollback()


# ============================================================
# Fixtures utilitaires
# ============================================================
@pytest_asyncio.fixture(scope="function")
async def clean_database(async_test_db: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """
    Fixture qui assure une base de données propre pour chaque test.

    Exécute chaque test dans une transaction qui est rollbackée à la fin.
    """
    async with async_test_db.begin():
        yield async_test_db
        # La transaction sera rollbackée automatiquement à la sortie du contexte


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """
    Fixture pour le loop d'événements asyncio.
    Nécessaire pour les tests asynchrones.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


# ============================================================
# Helpers pour les tests
# ============================================================
async def truncate_all_tables(session: AsyncSession) -> None:
    """
    Supprime toutes les données des tables pour un nettoyage complet.

    À utiliser avec prudence - principale aide pour les tests d'intégration.
    """
    # Récupérer toutes les tables
    tables = Base.metadata.sorted_tables

    # Désactiver les contraintes de clés étrangères
    await session.execute(text("SET CONSTRAINTS ALL DEFERRED"))

    # Supprimer les données de chaque table dans l'ordre inverse
    for table in reversed(tables):
        await session.execute(table.delete())

    await session.commit()


async def seed_test_data(session: AsyncSession) -> None:
    """
    Remplit la base de données avec des données de test standard.

    À personnaliser selon les besoins des tests.
    """
    from app.models import User, Studio, StudioMembership
    import uuid

    # Créer un studio de test
    studio_id = uuid.uuid4()
    studio = Studio(
        id=studio_id,
        name="Studio de Test",
        slug="test-studio",
    )
    session.add(studio)

    # Créer un utilisateur de test
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="test@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test$hashed",
        role="adaptateur",
        is_active=True,
    )
    session.add(user)

    # Créer une membership
    membership = StudioMembership(
        id=uuid.uuid4(),
        studio_id=studio_id,
        user_id=user_id,
        role="member",
    )
    session.add(membership)

    await session.commit()

    return {"studio_id": studio_id, "user_id": user_id}
