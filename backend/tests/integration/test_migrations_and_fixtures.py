"""
Test d'intégration migrations + fixtures (§9.7 CDC) — G-011.

Condition d'achèvement : une CI part d'une base PostgreSQL vide, monte jusqu'à
`head`, charge les fixtures, effectue un downgrade/upgrade supporté et valide
l'intégrité des données.

Démarre un PostgreSQL 16 embarqué (`pgserver`), exécute la chaîne Alembic réelle
(`alembic.command.upgrade`/`downgrade` via env.py), charge les fixtures
versionnées, et vérifie l'intégrité des données à travers un round-trip
downgrade/upgrade.

Skip automatique si PostgreSQL embarqué ou psycopg2 indisponible.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")
pgserver = pytest.importorskip("pgserver")


REPO = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI = REPO / "alembic.ini"
ALEMBIC_DIR = REPO / "alembic"


def _cfg(async_uri: str):
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    # env.py lit ALEMBIC_DATABASE_URL en priorité.
    os.environ["ALEMBIC_DATABASE_URL"] = async_uri
    return cfg


@pytest.fixture(scope="module")
def pg():
    srv = pgserver.get_server(Path("/tmp/rythmo_mig_fixtures_pg"), cleanup_mode="delete")
    uri = srv.get_uri()
    socket_dir = uri.split("host=")[-1]
    yield {
        "async_uri": uri.replace("postgresql://", "postgresql+asyncpg://"),
        "sync_uri": uri,  # postgres superuser, psycopg2
        "socket_dir": socket_dir,
    }
    srv.cleanup()


# ------------------------------------------------------------------
# 1. Schéma : base vide → head
# ------------------------------------------------------------------
def test_upgrade_head_from_empty_database(pg):
    """CI : une base PostgreSQL vide monte jusqu'à `head` sans erreur."""
    from alembic import command
    from alembic.script import ScriptDirectory

    cfg = _cfg(pg["async_uri"])
    command.upgrade(cfg, "head")

    head = ScriptDirectory.from_config(cfg).get_current_head()
    conn = psycopg2.connect(host=pg["socket_dir"], dbname="postgres", user="postgres")
    try:
        cur = conn.cursor()
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] == head, "alembic_version doit pointer sur head"
        # Tables critiques présentes
        for table in (
            "studios", "users", "projects", "replicas", "rythmo_bands",
            "user_preferences", "teams", "tasks", "media_assets",
        ):
            cur.execute(
                "SELECT to_regclass(%s)", (f"public.{table}",)
            )
            assert cur.fetchone()[0] == table, f"Table {table} manquante après upgrade"
    finally:
        conn.close()


# ------------------------------------------------------------------
# 2. Cohérence schéma migré vs modèles (anti-dérive)
# ------------------------------------------------------------------
def test_migrated_schema_matches_models(pg):
    """
    Le schéma produit par les migrations jusqu'à `head` doit correspondre aux
    modèles (toutes les tables et colonnes attendues sont présentes). Ce test
    aurait détecté les dérives historiques (table `replicas` manquante,
    colonne `media_assets.status` manquante) que `create_all` masquait.
    """
    from alembic import command
    from sqlalchemy import create_engine, inspect
    from app.models.base import Base
    import app.models  # noqa: F401
    import app.core.database  # noqa: F401

    command.upgrade(_cfg(pg["async_uri"]), "head")
    eng = create_engine(pg["sync_uri"])
    try:
        insp = inspect(eng)
        mig_tables = set(insp.get_table_names())
        missing_tables = sorted(
            {t.name for t in Base.metadata.sorted_tables} - mig_tables
            - {"alembic_version"}
        )
        assert not missing_tables, f"Tables modèles absentes du schéma migré: {missing_tables}"

        missing_cols = []
        for table in Base.metadata.sorted_tables:
            if table.name not in mig_tables:
                continue
            mig_cols = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in mig_cols:
                    missing_cols.append(f"{table.name}.{col.name}")
        assert not missing_cols, (
            f"Colonnes modèles absentes du schéma migré: {missing_cols}"
        )
    finally:
        eng.dispose()


# ------------------------------------------------------------------
# 3. Fixtures : chargement + intégrité
# ------------------------------------------------------------------
def test_fixtures_load_and_integrity(pg):
    """Les fixtures versionnées se chargent sur un schéma migré et sont cohérentes."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.fixtures.seed import fixtures_summary, load_fixtures

    eng = create_engine(pg["sync_uri"])
    try:
        with Session(eng) as session:
            ids = load_fixtures(session)
            assert len(ids["studios"]) == 2
            assert len(ids["users"]) == 3

        with Session(eng) as session:
            counts = fixtures_summary(session)
        # Comptes attendus du jeu de données de référence
        assert counts["studios"] == 2
        assert counts["users"] == 3
        assert counts["studio_memberships"] == 3
        assert counts["user_preferences"] == 1
        assert counts["project_folders"] == 1
        assert counts["project_tags"] == 1
        assert counts["projects"] == 1
        assert counts["media_assets"] == 1
        assert counts["rythmo_bands"] == 1
        assert counts["replicas"] == 2
        assert counts["teams"] == 1
        assert counts["team_memberships"] == 1
        assert counts["tasks"] == 1
    finally:
        eng.dispose()


# ------------------------------------------------------------------
# 3. Round-trip downgrade/upgrade supporté + intégrité des données
# ------------------------------------------------------------------
def test_supported_downgrade_upgrade_preserves_data(pg):
    """Downgrade supporté puis upgrade : les données fixtures sont préservées."""
    from alembic import command
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.fixtures.seed import clear_fixtures, fixtures_summary, load_fixtures

    eng = create_engine(pg["sync_uri"])
    try:
        with Session(eng) as session:
            load_fixtures(session)
            before = fixtures_summary(session)
    finally:
        eng.dispose()

    cfg = _cfg(pg["async_uri"])
    # Downgrade de 2 révisions (005 indexes, 004 RLS) — les tables et données
    # restent intactes (aucune table n'est supprimée sur cette plage).
    command.downgrade(cfg, "-2")
    # Re-upgrade vers head (recrée les index + les politiques RLS).
    command.upgrade(cfg, "head")

    eng = create_engine(pg["sync_uri"])
    try:
        with Session(eng) as session:
            after = fixtures_summary(session)
    finally:
        eng.dispose()

    assert after == before, (
        f"L'intégrité des données doit être préservée après downgrade/upgrade.\n"
        f"Avant: {before}\nAprès: {after}"
    )


# ------------------------------------------------------------------
# 4. Réversibilité complète de la chaîne (base → head → base → head)
# ------------------------------------------------------------------
def test_full_chain_reversible_schema_only(pg):
    """La chaîne complète est réversible : head → base → head (schéma seul)."""
    from alembic import command
    from alembic.script import ScriptDirectory

    cfg = _cfg(pg["async_uri"])
    head = ScriptDirectory.from_config(cfg).get_current_head()

    # Repart d'un état propre (le test précédent a laissé des données ; on purge
    # le schéma en repassant à base puis en remontant à head).
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    conn = psycopg2.connect(host=pg["socket_dir"], dbname="postgres", user="postgres")
    try:
        cur = conn.cursor()
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] == head
        cur.execute("SELECT to_regclass('public.replicas')")
        assert cur.fetchone()[0] == "replicas"
    finally:
        conn.close()
