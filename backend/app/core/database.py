"""
Base de données asynchrone SQLAlchemy 2.0 + asyncpg (§9.1, §18.4 CDC)

Remplace le moteur synchrone SQLite par défaut par:
- SQLAlchemy 2.0 asynchrone avec asyncpg pour PostgreSQL 16
- Sessions async avec AsyncSession
- Profil SQLite asynchrone (aiosqlite) réservé aux tests unitaires
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass, sessionmaker as sync_sessionmaker

from app.core.config import get_settings

# Import de Base depuis les modèles pour garantir unicité (§9.1)
# Tous les modèles dérivent de cette Base
from app.models.base import Base as _Base

# Base déclarative - utilisée pour les opérations de métadonnées
# (create_all, drop_all, etc.)
Base = _Base

# Import des modèles pour que Base.metadata les connaisse (§9.1)
# Ces imports doivent être absolus pour être exécutés au chargement du module
from app.models import (  # noqa: F401
    Studio,
    User,
    StudioMembership,
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
    StudioInvitation,
    Comment,
    AuditLog,
    SecurityAlert,
    SilenceEvent,
    EmotionTag,
    TypographicProfile,
    LipSyncFrame,
    LipSyncResult,
    AnonymizedCorrection,
    SsoConfiguration,
    ReplicaCrdtState,
    ReplicaCrdtOperation,
    ApiKey,
    WebhookEndpoint,
    WebhookDelivery,
    # §16.1–§16.3
    UserPreferences,
    ProjectFolder,
    ProjectTag,
    project_tags,
    Team,
    TeamMembership,
    Task,
)


# ============================================================
# Initialisation paresseuse des moteurs (§9.1)
# ============================================================
# Les moteurs sont créés à la première utilisation pour garantir
# que Base.metadata est entièrement peuplé avant la création.

_engine_cache: AsyncEngine | None = None
_test_engine_cache: AsyncEngine | None = None
_async_session_factory_cache: async_sessionmaker[AsyncSession] | None = None
_test_session_factory_cache: async_sessionmaker[AsyncSession] | None = None


def _get_engine_url(for_test: bool = False) -> str:
    """
    Retourne l'URL du moteur de base de données.

    Args:
        for_test: Si True, retourne l'URL SQLite asynchrone pour les tests.

    Returns:
        URL SQLAlchemy asynchrone (postgresql+asyncpg://... ou sqlite+aiosqlite://...)
    """
    settings = get_settings()
    return settings.get_database_url(for_test=for_test)


def create_engine(for_test: bool = False) -> AsyncEngine:
    """
    Crée le moteur SQLAlchemy asynchrone (avec caching).

    Args:
        for_test: Si True, utilise SQLite en mémoire avec aiosqlite pour les tests.

    Returns:
        AsyncEngine configuré pour le moteur asynchrone approprié.
    """
    global _engine_cache, _test_engine_cache

    # Retourner le moteur mis en cache si disponible
    if for_test:
        if _test_engine_cache is not None:
            return _test_engine_cache
    else:
        if _engine_cache is not None:
            return _engine_cache

    url = _get_engine_url(for_test=for_test)
    settings = get_settings()

    # Configuration commune pour tous les moteurs
    engine_kwargs: dict = {
        "echo": False,
    }

    # Optimisations spécifiques à PostgreSQL + asyncpg
    if "postgresql" in url:
        engine_kwargs.update({
            "pool_pre_ping": True,  # Vérifie la connexion avant utilisation
            "pool_size": 10,        # Taille du pool de connexions
            "max_overflow": 20,     # Connexions supplémentaires en cas de pic
            "pool_recycle": 3600,   # Recyclage des connexions toutes les heures
            "pool_timeout": 30,     # Timeout d'attente de connexion
        })

    # Configuration spécifique à SQLite (tests)
    elif "sqlite" in url:
        engine_kwargs.update({
            "poolclass": None,  # Pas de pool pour SQLite en mémoire
        })

    engine = create_async_engine(url, **engine_kwargs)

    # Mettre en cache le moteur
    if for_test:
        _test_engine_cache = engine
    else:
        _engine_cache = engine

    return engine


def create_engine_fresh(for_test: bool = False) -> AsyncEngine:
    """
    Crée un nouveau moteur SQLAlchemy asynchrone (sans caching).
    Utilisé pour les tests qui nécessitent un moteur frais.

    Args:
        for_test: Si True, utilise SQLite en mémoire avec aiosqlite pour les tests.

    Returns:
        Nouveau AsyncEngine.
    """
    url = _get_engine_url(for_test=for_test)

    engine_kwargs: dict = {
        "echo": False,
    }

    if "postgresql" in url:
        engine_kwargs.update({
            "pool_pre_ping": True,
            "pool_size": 5,
            "max_overflow": 10,
            "pool_recycle": 3600,
            "pool_timeout": 30,
        })
    elif "sqlite" in url:
        engine_kwargs.update({
            "poolclass": None,
        })

    return create_async_engine(url, **engine_kwargs)


# ============================================================
# Accès aux moteurs (initialisation paresseuse)
# ============================================================
def get_engine(for_test: bool = False) -> AsyncEngine:
    """
    Retourne le moteur de base de données (avec initialisation paresseuse).

    Args:
        for_test: Si True, retourne le moteur de test SQLite.

    Returns:
        AsyncEngine configuré.
    """
    if for_test:
        return create_engine(for_test=True)
    return create_engine(for_test=False)


def get_test_engine() -> AsyncEngine:
    """Retourne le moteur de test (SQLite asynchrone)."""
    return create_engine(for_test=True)


# ============================================================
# Fabriques de sessions asynchrones
# ============================================================
def get_async_session_factory(for_test: bool = False) -> async_sessionmaker[AsyncSession]:
    """
    Retourne la fabrique de sessions asynchrones (avec initialisation paresseuse).

    Args:
        for_test: Si True, retourne la fabrique pour SQLite de test.

    Returns:
        async_sessionmaker configurée pour le bon moteur.
    """
    global _async_session_factory_cache, _test_session_factory_cache

    if for_test:
        if _test_session_factory_cache is not None:
            return _test_session_factory_cache
        engine = get_test_engine()
        factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        _test_session_factory_cache = factory
        return factory
    else:
        if _async_session_factory_cache is not None:
            return _async_session_factory_cache
        engine = get_engine(for_test=False)
        factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        _async_session_factory_cache = factory
        return factory


# ============================================================
# Dépendances pour les routes FastAPI
# ============================================================
def get_db() -> Generator:
    """
    Dépendance FastAPI : injecte une session de base de données synchrone.

    Toutes les routes utilisent l'API synchrone SQLAlchemy (`db.query()`),
    aussi la dépendance produit-elle une `Session` synchrone (via `SessionLocal`).

    Yields:
        Session: Session SQLAlchemy synchrone.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_test_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dépendance pour les tests unitaires utilisant SQLite asynchrone.

    Yields:
        AsyncSession: Session SQLAlchemy asynchrone pour tests.
    """
    factory = get_async_session_factory(for_test=True)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()


# ============================================================
# Contexte de session (pour les scripts et tasks)
# ============================================================
@asynccontextmanager
async def database_session(for_test: bool = False) -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager pour gérer une session de base de données asynchrone.

    Utilise ce contexte dans les scripts ou tasks qui ne sont pas des routes FastAPI.

    Args:
        for_test: Si True, utilise la session de test (SQLite).

    Yields:
        AsyncSession: Session SQLAlchemy asynchrone.

    Example:
        async with database_session() as session:
            result = await session.execute(select(User))
    """
    factory = get_async_session_factory(for_test=for_test)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()


# ============================================================
# Initialisation et migration
# ============================================================
def init_db() -> None:
    """
    Initialise la base de données en créant toutes les tables.

    ATTENTION: Cette fonction est réservée aux tests unitaires.
    En production, utilisez Alembic pour les migrations.
    """
    Base.metadata.create_all(bind=_get_sync_engine())


def init_test_db() -> None:
    """
    Initialise la base de données de test en créant toutes les tables.

    Utilisée exclusivement pour les tests unitaires avec SQLite.
    """
    Base.metadata.create_all(bind=_get_sync_engine())


async def close_engine() -> None:
    """Ferme proprement le moteur de base de données."""
    global _engine_cache
    if _engine_cache is not None:
        await _engine_cache.dispose()
        _engine_cache = None


async def close_test_engine() -> None:
    """Ferme proprement le moteur de test."""
    global _test_engine_cache
    if _test_engine_cache is not None:
        await _test_engine_cache.dispose()
        _test_engine_cache = None


async def dispose_all() -> None:
    """Ferme tous les moteurs."""
    await close_engine()
    await close_test_engine()


# ============================================================
# Export pour compatibilité avec le code existant
# ============================================================

def get_engine_url() -> str:
    """
    Retourne l'URL de base de données (par défaut, pour la production).
    Utilisé par certains modules qui ont besoin de l'URL directement.
    """
    return _get_engine_url(for_test=False)


# ============================================================
# Compatibilité legacy (déprécié, à supprimer après migration complète)
# ============================================================

# Moteur synchrone mis en cache pour la compatibilité legacy
_sync_engine_cache: object = None


def _get_sync_engine() -> object:
    """
    Retourne le moteur synchrone.

    Toute la couche d'accès aux données (routes FastAPI, repositories, tests
    d'intégration) utilise l'API synchrone de SQLAlchemy 2.0 (`db.query()` /
    `Session`). Ce moteur synchrone est donc la source de données réelle de
    l'application. Il est créé paresseusement au premier accès.

    Pour SQLite (tests), `check_same_thread=False` permet l'usage depuis le
    threadpool de FastAPI/TestClient ; `StaticPool` garantit qu'une base
    `:memory:` est partagée entre toutes les sessions.
    """
    global _sync_engine_cache
    if _sync_engine_cache is not None:
        return _sync_engine_cache

    from sqlalchemy import create_engine as create_sync_engine
    from sqlalchemy.pool import StaticPool

    url = _get_engine_url(for_test=False)
    sync_url = url.replace("+asyncpg", "").replace("+aiosqlite", "")

    kwargs: dict = {"future": True}
    if sync_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in sync_url:
            kwargs["poolclass"] = StaticPool

    _sync_engine_cache = create_sync_engine(sync_url, **kwargs)
    return _sync_engine_cache


def get_sync_session_factory() -> sync_sessionmaker:
    """
    Retourne la fabrique de sessions synchrones pour compatibilité legacy.
    """
    from sqlalchemy.orm import sessionmaker as sync_sessionmaker

    sync_engine = _get_sync_engine()
    return sync_sessionmaker(bind=sync_engine, expire_on_commit=False)


# SessionLocal - Alias pour compatibilité avec le code existant (§18.4)
# PEUT ÊTRE SUPPRIMÉ APRÈS MIGRATION COMPLÈTE VERS ASYNC
# Utilisation paresseuse via __getattr__ pour éviter l'erreur d'import si psycopg2 n'est pas installé

class _SessionLocalProxy:
    """
    Proxy paresseux pour SessionLocal.
    Crée la session synchrone uniquement au premier usage.
    Permet à l'application de démarrer même si psycopg2 n'est pas installé.
    """

    _factory = None

    def __call__(self, *args, **kwargs):
        if self._factory is None:
            self._factory = get_sync_session_factory()
        return self._factory(*args, **kwargs)


SessionLocal = _SessionLocalProxy()


# engine - Proxy pour compatibilité avec les tests existants.
# Délègue au moteur SYNCHRONE (les routes/repositories/tests utilisent l'API
# synchrone : `Base.metadata.create_all(bind=engine)`, `engine.connect()`, etc.).
class _EngineProxy:
    """
    Proxy pour le moteur synchrone.
    Permet aux tests existants d'utiliser 'engine' avec une initialisation
    paresseuse.
    """

    _engine = None

    def __getattr__(self, name):
        if self._engine is None:
            self._engine = _get_sync_engine()
        return getattr(self._engine, name)

    def dispose(self):
        if self._engine is not None:
            try:
                self._engine.dispose()
            except Exception:
                pass

    async def aiosync_dispose(self):
        """Dispose du moteur (compatibilité async)."""
        self.dispose()
        self._engine = None


# Alias pour compatibilité - les tests peuvent utiliser engine.connect() etc.
engine = _EngineProxy()


def get_db_sync() -> Generator:
    """
    [DEPRECATED] Générateur de session synchrone pour compatibilité temporaire.

    Ce générateur est maintenu uniquement pour permettre une migration progressive.
    Tout nouveau code doit utiliser get_db() (asynchrone).
    """
    import warnings
    warnings.warn(
        "get_db_sync() est déprécié. Utilisez get_db() asynchrone.",
        DeprecationWarning,
        stacklevel=2,
    )

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


async def close_sync_engine() -> None:
    """Ferme le moteur synchrone de compatibilité."""
    global _sync_engine_cache
    if _sync_engine_cache is not None:
        _sync_engine_cache.dispose()
        _sync_engine_cache = None
