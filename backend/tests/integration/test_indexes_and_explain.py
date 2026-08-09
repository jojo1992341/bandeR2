"""
Tests d'intégration indexation PostgreSQL (§9.5 CDC) — G-010.

Condition d'achèvement :
- une inspection PostgreSQL confirme les index attendus ;
- un EXPLAIN de chargement timeline et de recherche utilise les index prévus.

Démarre un PostgreSQL 16 embarqué (`pgserver`), crée le schéma, applique la
migration `005_optimize_indexes_uuid7` (et l'index full-text de recherche),
seed des données, puis inspecte `pg_indexes` et analyse des plans EXPLAIN.

Skip automatique si PostgreSQL embarqué ou psycopg2 indisponible.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")
pgserver = pytest.importorskip("pgserver")


@pytest.fixture(scope="module")
def pgdb():
    from sqlalchemy import create_engine
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.models.base import Base
    import app.models  # noqa: F401
    import app.core.database  # noqa: F401

    srv = pgserver.get_server(Path("/tmp/rythmo_idx_pg"), cleanup_mode="delete")
    uri = srv.get_uri()
    socket_dir = uri.split("host=")[-1]

    eng = create_engine(uri)
    # 1. Schéma + index définis côté modèle (composite, order_index, GIN).
    Base.metadata.create_all(eng)

    # 2. Migration 005 (index de performance §9.5) — idempotente.
    mig_path = (
        Path(__file__).resolve().parent.parent.parent
        / "alembic"
        / "versions"
        / "005_optimize_indexes_uuid7.py"
    )
    spec = importlib.util.spec_from_file_location("idx_migration_005", mig_path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    with eng.connect() as conn:
        from sqlalchemy import text as _text

        mc = MigrationContext.configure(conn)
        mig.apply_index_ddl(Operations(mc))
        # 3. Index full-text de recherche (équivalent migration v3w4) pour l'EXPLAIN.
        conn.execute(
            _text(
                "CREATE INDEX IF NOT EXISTS ix_replicas_text_tsvector "
                "ON replicas USING GIN (to_tsvector('french', text));"
            )
        )
        conn.commit()
    eng.dispose()

    yield {"socket_dir": socket_dir, "dbname": "postgres"}

    srv.cleanup()


def _conn(pgdb):
    c = psycopg2.connect(host=pgdb["socket_dir"], dbname=pgdb["dbname"], user="postgres")
    c.autocommit = True
    return c


@pytest.fixture(scope="module")
def seeded(pgdb):
    studio = uuid.uuid4()
    project = uuid.uuid4()
    media = uuid.uuid4()
    # Plusieurs bandes : la requête d'une bande devient sélective (favorise
    # l'usage de l'index composite).
    bands = [uuid.uuid4() for _ in range(5)]
    admin = _conn(pgdb)
    try:
        cur = admin.cursor()
        cur.execute("INSERT INTO studios (id,name,plan) VALUES (%s,'S','pro')", (studio,))
        cur.execute(
            "INSERT INTO projects (id,studio_id,title,status) VALUES (%s,%s,'P','Cree')",
            (project, studio),
        )
        cur.execute(
            "INSERT INTO media_assets (id,project_id,storage_path,status) VALUES (%s,%s,'m','confirmed')",
            (media, project),
        )
        for b in bands:
            cur.execute(
                "INSERT INTO rythmo_bands (id,project_id,version_number,status,is_master,metadata) "
                "VALUES (%s,%s,1,'draft',false,'{}'::jsonb)",
                (b, project),
            )
        rows = []
        for i in range(2000):
            rid = uuid.uuid4()
            b = bands[i % len(bands)]
            txt = "bonjour le monde" if i % 5 == 0 else f"réplique numéro {i}"
            typo = "'{\"italique\": true}'" if i % 10 == 0 else "NULL"
            rows.append(
                f"('{rid}','{b}','{media}','{txt}',{i * 100},{i * 100 + 90},{i},{typo},false,false,1)"
            )
        cur.execute(
            "INSERT INTO replicas (id,rythmo_band_id,media_id,text,start_ms,end_ms,order_index,typo_codes,is_manually_edited,breath_marker,version) VALUES "
            + ",".join(rows)
        )
        cur.execute("ANALYZE replicas;")
        cur.execute("ANALYZE rythmo_bands;")
    finally:
        admin.close()
    return {"band": bands[0], "studio": studio, "project": project}


def _explain(cur, sql, params=None):
    # Désactive le Seq Scan pour révéler l'index couvrant la requête (technique
    # standard de test d'indexation : si l'index ne couvre pas, le plan ne
    # l'utilisera pas malgré enable_seqscan=off).
    cur.execute("SET enable_seqscan = off")
    cur.execute("EXPLAIN " + sql, params or ())
    return "\n".join(r[0] for r in cur.fetchall())


# ------------------------------------------------------------------
# 1. Inspection des index attendus
# ------------------------------------------------------------------
def test_expected_indexes_exist(pgdb, seeded):
    expected = {
        "ix_replicas_band_start_ms",      # composite (timeline)
        "ix_replicas_order_index",        # tri des répliques
        "ix_replicas_typo_codes_gin",     # GIN JSONB typo_codes
        "ix_rythmo_bands_metadata_gin",   # GIN JSONB métadonnées IA
        "ix_replicas_text_tsvector",      # GIN full-text recherche
    }
    conn = _conn(pgdb)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public'"
        )
        present = {r[0] for r in cur.fetchall()}
        missing = expected - present
        assert not missing, f"Index manquants: {missing}"
    finally:
        conn.close()


def test_fk_indexes_exist(pgdb, seeded):
    """§9.5 : index B-Tree sur les FK (rythmo_band_id, media_id, speaker_id).

    rythmo_band_id est couvert par l'index composite (préfixe gauche), d'où
    l'absence d'index simple dédié (cf. §9.5 / optimisation).
    """
    conn = _conn(pgdb)
    try:
        cur = conn.cursor()
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename='replicas'")
        names = {r[0] for r in cur.fetchall()}
        assert "ix_replicas_media_id" in names
        assert "ix_replicas_speaker_id" in names
        # rythmo_band_id couvert par le composite
        assert "ix_replicas_band_start_ms" in names
        assert "ix_replicas_rythmo_band_id" not in names, (
            "l'index simple rythmo_band_id est redondant (couvert par le composite)"
        )
    finally:
        conn.close()


def test_composite_index_columns(pgdb, seeded):
    """L'index composite porte bien (rythmo_band_id, start_ms)."""
    conn = _conn(pgdb)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname='ix_replicas_band_start_ms'"
        )
        definition = cur.fetchone()[0].lower()
        assert "rythmo_band_id" in definition and "start_ms" in definition
    finally:
        conn.close()


# ------------------------------------------------------------------
# 2. EXPLAIN : chargement timeline utilise l'index composite
# ------------------------------------------------------------------
def test_explain_timeline_uses_composite_index(pgdb, seeded):
    """Le chargement timeline fenêtré (LIMIT) utilise l'index composite, sans Sort."""
    conn = _conn(pgdb)
    try:
        cur = conn.cursor()
        plan = _explain(
            cur,
            "SELECT id, text, start_ms FROM replicas "
            "WHERE rythmo_band_id = %s ORDER BY start_ms LIMIT 100",
            (str(seeded["band"]),),
        )
        assert "ix_replicas_band_start_ms" in plan, (
            f"Le chargement timeline doit utiliser l'index composite. Plan:\n{plan}"
        )
        # L'index composite fournit déjà l'ordre → pas de Sort coûteux.
        assert "sort" not in plan.lower(), (
            f"L'index composite doit éviter un Sort (accès ordonné). Plan:\n{plan}"
        )
    finally:
        conn.close()


# ------------------------------------------------------------------
# 3. EXPLAIN : la recherche full-text utilise l'index GIN
# ------------------------------------------------------------------
def test_explain_search_uses_gin_index(pgdb, seeded):
    conn = _conn(pgdb)
    try:
        cur = conn.cursor()
        plan = _explain(
            cur,
            "SELECT id FROM replicas "
            "WHERE to_tsvector('french', text) @@ plainto_tsquery('french', 'bonjour')",
        )
        assert "ix_replicas_text_tsvector" in plan, (
            f"La recherche full-text doit utiliser l'index GIN. Plan:\n{plan}"
        )
        assert "bitmap" in plan.lower() or "index scan" in plan.lower()
    finally:
        conn.close()


def test_explain_typo_codes_uses_gin_index(pgdb, seeded):
    """Le filtrage JSONB typo_codes utilise l'index GIN (containment @>)."""
    conn = _conn(pgdb)
    try:
        cur = conn.cursor()
        plan = _explain(
            cur,
            "SELECT id FROM replicas WHERE typo_codes @> '{\"italique\": true}'::jsonb",
        )
        assert "ix_replicas_typo_codes_gin" in plan, (
            f"Le filtrage typo_codes doit utiliser le GIN. Plan:\n{plan}"
        )
    finally:
        conn.close()


# ------------------------------------------------------------------
# 4. L'index composite couvre aussi le filtrage par plage temporelle
# ------------------------------------------------------------------
def test_explain_timeline_range_uses_composite_index(pgdb, seeded):
    """Le chargement d'une plage de timeline (start_ms borné) utilise l'index composite."""
    conn = _conn(pgdb)
    try:
        cur = conn.cursor()
        plan = _explain(
            cur,
            "SELECT id FROM replicas WHERE rythmo_band_id = %s "
            "AND start_ms BETWEEN 1000 AND 5000 ORDER BY start_ms LIMIT 50",
            (str(seeded["band"]),),
        )
        assert "ix_replicas_band_start_ms" in plan, (
            f"Le filtrage par plage temporelle doit utiliser l'index composite. Plan:\n{plan}"
        )
    finally:
        conn.close()
