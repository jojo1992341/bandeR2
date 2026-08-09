"""
Contexte tenant transactionnel pour PostgreSQL Row-Level Security (§9.6 CDC).

Le contexte `app.current_studio_id` est une GUC (Grand Unified Configuration)
PostgreSQL consommée par les politiques RLS (migration `004_enable_rls`).
Positionner cette variable sur une connexion restreint toutes les requêtes
(lecture/écriture) aux lignes du studio courant — même via SQL brut — tant que
la connexion utilise le **rôle applicatif non-superuser** (`rythmoai_app`).

Deux variantes :
- `set_studio_context` : `SET LOCAL` → contexte **transactionnel** (recommandé) ;
  la variable est automatiquement réinitialisée en fin de transaction, ce qui
  évite toute fuite entre requêtes dans un pool de connexions.
- `set_studio_context_session` : `SET` → contexte de session (legacy).

Sur SQLite (tests unitaires sans RLS), ces fonctions sont des no-ops.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def _dialect_is_postgres(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind) and bind.dialect.name != "sqlite"


def set_studio_context(db: Session, studio_id: uuid.UUID) -> None:
    """
    Positionne le contexte tenant pour la **transaction courante** (SET LOCAL).

    À utiliser au début de chaque unité de travail (requête) : la variable est
    automatiquement levée au COMMIT/ROLLBACK, garantissant l'isolation entre
    requêtes successives réutilisant la même connexion (pool).

    No-op sur SQLite (pas de RLS).
    """
    if not _dialect_is_postgres(db):
        return
    db.execute(
        text("SET LOCAL app.current_studio_id = :sid"),
        {"sid": str(studio_id)},
    )


def set_studio_context_session(db: Session, studio_id: uuid.UUID) -> None:
    """
    Positionne le contexte tenant pour toute la **session** PostgreSQL (SET).

    Variante legacy / scripts : la variable persiste jusqu'à la déconnexion.
    À éviter dans une API avec pool de connexions (préférer `set_studio_context`).
    """
    if not _dialect_is_postgres(db):
        return
    db.execute(
        text("SET app.current_studio_id = :sid"),
        {"sid": str(studio_id)},
    )


def clear_studio_context(db: Session) -> None:
    """Réinitialise le contexte tenant de la transaction courante."""
    if not _dialect_is_postgres(db):
        return
    db.execute(text("RESET app.current_studio_id"))
