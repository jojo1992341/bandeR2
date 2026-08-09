"""optimize indexes & uuid v7 §9.5

Aligne l'indexation sur le CDC §9.5 :
- Index composite (rythmo_band_id, start_ms) pour le chargement de la timeline
  dans l'éditeur ;
- Index B-Tree sur order_index (tri stable des répliques) ;
- Colonnes JSON promues en JSONB + index GIN sur typo_codes (replicas) et les
  métadonnées IA brutes (rythmo_bands.metadata) pour le filtrage avancé.

Les UUID v7 (ordonnés temporellement) sont appliqués côté applicatif
(`app.core.uuid7`) pour les nouvelles clés primaires ; les UUID v4 existants
cohabitent sans migration des données.

Idempotent (IF NOT EXISTS / ALTER TYPE jsonb sans perte). La fonction
`apply_index_ddl(operations)` est réutilisée par les tests (instance
`Operations` liée à une connexion PostgreSQL embarquée).

Revision ID: 005_optimize_indexes_uuid7
Revises: 004_enable_rls
Create Date: 2026-08-09
"""

from __future__ import annotations

from typing import Protocol

from alembic import op


revision = "005_optimize_indexes_uuid7"
down_revision = "004_enable_rls"
branch_labels = None
depends_on = None


class _OperationsLike(Protocol):
    def execute(self, sql: str) -> None: ...


def _is_postgres(operations: _OperationsLike) -> bool:
    bind = getattr(operations, "get_bind", lambda: None)()
    return bool(bind) and bind.dialect.name == "postgresql"


def apply_index_ddl(operations: _OperationsLike) -> None:
    """Applique les index de performance §9.5 (idempotent, PostgreSQL)."""
    if not _is_postgres(operations):
        # Sur SQLite (tests unitaires) ces index GIN/composites ne sont pas
        # pertinents ; ils sont déjà créés par create_all() côté modèle.
        return

    exe = operations.execute

    # 1. Promouvoir les colonnes JSON en JSONB (prérequis au GIN).
    exe(
        "ALTER TABLE replicas ALTER COLUMN typo_codes "
        "TYPE jsonb USING typo_codes::jsonb;"
    )
    exe(
        "ALTER TABLE rythmo_bands ALTER COLUMN metadata "
        "TYPE jsonb USING metadata::jsonb;"
    )

    # 2. Index composite (rythmo_band_id, start_ms) — chargement timeline.
    exe(
        "CREATE INDEX IF NOT EXISTS ix_replicas_band_start_ms "
        "ON replicas (rythmo_band_id, start_ms);"
    )
    # L'index simple ix_replicas_rythmo_band_id devient redondant (le composite
    # couvre la FK par préfixe gauche) : on le supprime pour que le planificateur
    # privilégie l'index composite (et évite un Sort sur la timeline).
    exe("DROP INDEX IF EXISTS ix_replicas_rythmo_band_id;")

    # 3. Index B-Tree sur order_index — tri stable des répliques.
    exe(
        "CREATE INDEX IF NOT EXISTS ix_replicas_order_index "
        "ON replicas (order_index);"
    )

    # 4. Index GIN sur les colonnes JSONB (typo_codes, métadonnées IA brutes).
    exe(
        "CREATE INDEX IF NOT EXISTS ix_replicas_typo_codes_gin "
        "ON replicas USING gin (typo_codes);"
    )
    exe(
        "CREATE INDEX IF NOT EXISTS ix_rythmo_bands_metadata_gin "
        "ON rythmo_bands USING gin (metadata);"
    )


def rollback_index_ddl(operations: _OperationsLike) -> None:
    if not _is_postgres(operations):
        return
    exe = operations.execute
    for idx in (
        "ix_rythmo_bands_metadata_gin",
        "ix_replicas_typo_codes_gin",
        "ix_replicas_order_index",
        "ix_replicas_band_start_ms",
    ):
        exe(f"DROP INDEX IF EXISTS {idx};")


def upgrade() -> None:
    apply_index_ddl(op)


def downgrade() -> None:
    rollback_index_ddl(op)
