"""
Alembic environment configuration for async SQLAlchemy 2.0 + asyncpg.

Supports:
- PostgreSQL 16 with asyncpg (production)
- SQLite with aiosqlite (tests)
- Explicit .env loading via pydantic-settings
"""

from __future__ import annotations

import asyncio
import os
import sys

from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Ajoute le dossier backend au chemin système pour les imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.config import get_settings
from app.models.base import Base

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
target_metadata = Base.metadata


def get_database_url() -> str:
    """
    Récupère l'URL de base de données depuis la configuration.

    Priorité:
    1. Variable d'environnement ALEMBIC_DATABASE_URL
    2. DATABASE_URL depuis .env (via pydantic-settings)
    3. Construction depuis les composants DB_* (défaut PostgreSQL)
    """
    # Vérifier d'abord la variable d'environnement spécifique à Alembic
    alembic_url = os.getenv("ALEMBIC_DATABASE_URL")
    if alembic_url:
        return alembic_url

    # Fallback sur la configuration générale
    settings = get_settings()
    return settings.DATABASE_URL


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to
    the script output.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Exécute les migrations avec une connexion synchrone."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations in 'online' mode with async engine.

    Crée un moteur asynchrone et exécute les migrations via une connexion synchrone
    obtenue à partir du moteur asynchrone.
    """
    url = get_database_url()

    # Configuration du moteur asynchrone
    connectable = async_engine_from_config(
        {
            "sqlalchemy.url": url,
            "poolclass": pool.NullPool,
        },
        prefix="sqlalchemy.",
    )

    async with connectable.connect() as connection:
        # Exécuter les migrations via une connexion synchrone
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    # Utiliser le mode asynchrone pour PostgreSQL, synchrone pour SQLite
    url = get_database_url()

    if "postgresql" in url:
        # Mode asynchrone pour PostgreSQL
        asyncio.run(run_async_migrations())
    else:
        # Mode synchrone pour SQLite (tests)
        from sqlalchemy import create_engine

        sync_url = url.replace("+aiosqlite", "")
        connectable = create_engine(
            sync_url,
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            do_run_migrations(connection)

        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
