"""enable row-level security §9.6

Isolation multi-tenant renforcée par PostgreSQL Row-Level Security (§9.6 CDC).

Cette migration :
1. Crée un **rôle applicatif non-superuser** (`rythmoai_app`, NOBYPASSRLS) —
   condition indispensable pour que RLS s'applique (les superusers et le
   `BYPASSRLS` contournent toujours RLS). En production, l'application DOIT
   se connecter via ce rôle (et non `postgres`).
2. Accorde à ce rôle les privilèges nécessaires sur le schéma et les tables.
3. **Active ET force** RLS (`FORCE ROW LEVEL SECURITY`) sur les tables
   sensibles tenant-scopées : le `FORCE` soumet même le propriétaire de la
   table aux politiques.
4. Définit des politiques (`CREATE POLICY`) filtrant par
   `current_setting('app.current_studio_id')` :
   - tables porteuses d'un `studio_id` NOT NULL : isolation stricte ;
   - tables d'événements système (`audit_logs`, `security_alerts`) dont le
     `studio_id` est NULLABLE : le tenant voit ses événements + les événements
     globaux (studio_id IS NULL) ;
   - `media_assets` (sans studio_id direct) : isolation via jointure sur
     `projects`.

Le contexte tenant transactionnel est positionné par `app.core.rls_context`
(`SET LOCAL app.current_studio_id`).

La fonction `apply_rls_ddl(operations)` est factorisée afin d'être exécutée
both par Alembic (`upgrade()`) et par les tests (instance `Operations` liée à
une connexion).

Revision ID: 004_enable_rls
Revises: 003_add_preferences_org_teams_tasks
Create Date: 2026-08-09
"""

from __future__ import annotations

import os
from typing import Protocol

from alembic import op


revision = "004_enable_rls"
down_revision = "003_prefs_org_teams_tasks"
branch_labels = None
depends_on = None


APP_ROLE = "rythmoai_app"
# Mot de passe configurable (surcharge obligatoire en production via l'env).
APP_ROLE_PASSWORD = os.environ.get("RYTHMOAI_APP_PASSWORD", "rythmoai_app_dev")

# Tables tenant-scopées avec studio_id NOT NULL → isolation stricte.
DIRECT_STUDIO_TABLES = [
    "projects",
    "project_folders",
    "project_tags_def",
    "teams",
    "tasks",
    "subscriptions",
    "typographic_profiles",
    "sso_configurations",
    "api_keys",
    "studio_memberships",
    "studio_invitations",
    "anonymized_corrections",
]

# Tables d'événements système (studio_id NULLABLE).
NULLABLE_STUDIO_TABLES = [
    "audit_logs",
    "security_alerts",
]

# Table enfant sans studio_id direct : isolation via projects.
JOIN_PROJECT_TABLES = [
    "media_assets",
]


class _OperationsLike(Protocol):
    def execute(self, sql: str) -> None: ...


def _tenant_expr(table: str) -> str:
    """Expression RLS comparant studio_id au contexte tenant courant."""
    return (
        f"{table}.studio_id::text = "
        f"current_setting('app.current_studio_id', true)"
    )


def apply_rls_ddl(operations: _OperationsLike) -> None:
    """
    Applique l'ensemble du DDL RLS via l'objet `operations` fourni
    (Alembic `op` en migration, instance `Operations` en test).
    """
    exe = operations.execute

    # ------------------------------------------------------------------
    # 1. Rôle applicatif non-superuser (soumis à RLS).
    # ------------------------------------------------------------------
    exe(
        f"""DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} WITH LOGIN PASSWORD '{APP_ROLE_PASSWORD}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            ELSE
                ALTER ROLE {APP_ROLE} NOSUPERUSER NOBYPASSRLS;
            END IF;
        END
        $$;"""
    )

    # ------------------------------------------------------------------
    # 2. Privilèges du rôle applicatif.
    # ------------------------------------------------------------------
    exe(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE};")
    exe(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};"
    )
    exe(
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};"
    )
    # Privilèges par défaut pour les futures tables.
    exe(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE};"
    )

    # ------------------------------------------------------------------
    # 3-4. RLS strict sur les tables à studio_id NOT NULL.
    # ------------------------------------------------------------------
    for table in DIRECT_STUDIO_TABLES:
        expr = _tenant_expr(table)
        exe(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        exe(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        exe(
            f"""CREATE POLICY {table}_tenant_isolation ON {table}
                FOR ALL TO {APP_ROLE}
                USING ({expr})
                WITH CHECK ({expr});"""
        )

    # Tables d'événements système (studio_id NULLABLE).
    for table in NULLABLE_STUDIO_TABLES:
        expr = _tenant_expr(table)
        exe(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        exe(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        exe(
            f"""CREATE POLICY {table}_tenant_isolation ON {table}
                FOR ALL TO {APP_ROLE}
                USING ({table}.studio_id IS NULL OR {expr})
                WITH CHECK ({table}.studio_id IS NULL OR {expr});"""
        )

    # media_assets : isolation via jointure sur projects (lui-même RLS).
    for table in JOIN_PROJECT_TABLES:
        join_expr = (
            f"EXISTS (SELECT 1 FROM projects p "
            f"WHERE p.id = {table}.project_id "
            f"AND p.studio_id::text = current_setting('app.current_studio_id', true))"
        )
        exe(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        exe(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        exe(
            f"""CREATE POLICY {table}_tenant_isolation ON {table}
                FOR ALL TO {APP_ROLE}
                USING ({join_expr})
                WITH CHECK ({join_expr});"""
        )


def rollback_rls_ddl(operations: _OperationsLike) -> None:
    """Inverse `apply_rls_ddl` (désactive RLS, supprime les politiques)."""
    exe = operations.execute
    all_tables = DIRECT_STUDIO_TABLES + NULLABLE_STUDIO_TABLES + JOIN_PROJECT_TABLES
    for table in all_tables:
        exe(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
        exe(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        exe(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")


def upgrade() -> None:
    apply_rls_ddl(op)


def downgrade() -> None:
    rollback_rls_ddl(op)
