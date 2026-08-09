"""
Test d'intégration RLS PostgreSQL (§9.6 CDC) — G-009.

Condition d'achèvement : les migrations activent/forcent RLS ; deux connexions
de test avec des contextes studio distincts ne peuvent **jamais** lire, mettre
à jour ou supprimer les données de l'autre, même via SQL brut applicatif.

Ce test démarre un PostgreSQL 16 embarqué (via `pgserver`), applique le schéma
puis la migration RLS (`004_enable_rls.apply_rls_ddl`), et vérifie l'isolation
au niveau **moteur** (raw SQL exécuté en tant que rôle applicatif non-superuser
`rythmoai_app`, sujet à RLS). Les superusers contournant RLS, l'isolation n'est
prouvée que via ce rôle applicatif.

Skip automatique si PostgreSQL embarqué ou psycopg2 indisponible.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")
pgserver = pytest.importorskip("pgserver")


# ------------------------------------------------------------------
# Harnais : PostgreSQL embarqué + schéma + RLS
# ------------------------------------------------------------------
@pytest.fixture(scope="module")
def pg(request):
    """Démarre un PostgreSQL embarqué, crée le schéma et applique la migration RLS."""
    from sqlalchemy import create_engine
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.models.base import Base
    # Force le peuplement des métadonnées
    import app.models  # noqa: F401
    import app.core.database  # noqa: F401

    srv = pgserver.get_server(Path("/tmp/rythmo_rls_pg"), cleanup_mode="delete")
    superuser_uri = srv.get_uri()

    eng = create_engine(superuser_uri)
    # 1. Schéma (toutes les tables)
    Base.metadata.create_all(eng)

    # 2. Migration RLS (apply_rls_ddl via Operations lié à la connexion superuser)
    mig_path = (
        Path(__file__).resolve().parent.parent.parent
        / "alembic"
        / "versions"
        / "004_enable_rls.py"
    )
    spec = importlib.util.spec_from_file_location("rls_migration_004", mig_path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    with eng.connect() as conn:
        mc = MigrationContext.configure(conn)
        ops_ctx = Operations(mc)
        mig.apply_rls_ddl(ops_ctx)
        conn.commit()
    eng.dispose()

    # Extraire le répertoire du socket unix depuis l'URI (host=...)
    socket_dir = superuser_uri.split("host=")[-1]

    pg_info = {
        "socket_dir": socket_dir,
        "dbname": "postgres",
        "superuser_uri": superuser_uri,
    }

    yield pg_info

    srv.cleanup()


def _connect(pg_info, *, role="rythmoai_app", password="rythmoai_app_dev"):
    conn = psycopg2.connect(
        host=pg_info["socket_dir"],
        dbname=pg_info["dbname"],
        user=role,
        password=password,
    )
    conn.autocommit = False
    return conn


def _superuser_connect(pg_info):
    return _connect(pg_info, role="postgres", password="")


# ------------------------------------------------------------------
# Seed : deux studios, deux projets, deux médias
# ------------------------------------------------------------------
@pytest.fixture(scope="module")
def seeded(pg):
    info = pg
    studio_a = uuid.uuid4()
    studio_b = uuid.uuid4()
    proj_a = uuid.uuid4()
    proj_b = uuid.uuid4()
    media_a = uuid.uuid4()
    media_b = uuid.uuid4()

    admin = _superuser_connect(info)
    try:
        cur = admin.cursor()
        cur.execute(
            "INSERT INTO studios (id, name, plan) VALUES (%s,'Studio A','pro'),(%s,'Studio B','pro')",
            (studio_a, studio_b),
        )
        cur.execute(
            "INSERT INTO projects (id, studio_id, title, status) VALUES "
            "(%s,%s,'Projet A','Cree'),(%s,%s,'Projet B','Cree')",
            (proj_a, studio_a, proj_b, studio_b),
        )
        cur.execute(
            "INSERT INTO media_assets (id, project_id, storage_path, status) VALUES "
            "(%s,%s,'/tmp/a.mp4','confirmed'),(%s,%s,'/tmp/b.mp4','confirmed')",
            (media_a, proj_a, media_b, proj_b),
        )
        admin.commit()
    finally:
        admin.close()

    return {
        "studio_a": studio_a,
        "studio_b": studio_b,
        "proj_a": proj_a,
        "proj_b": proj_b,
        "media_a": media_a,
        "media_b": media_b,
    }


def _ids(cur):
    """Normalise les identifiants retournés (UUID ou str) en un set de str."""
    return {str(r[0]) for r in cur.fetchall()}


# ------------------------------------------------------------------
# Tests d'isolation RLS
# ------------------------------------------------------------------
def test_rls_select_isolated_by_tenant(pg, seeded):
    """Une connexion studio A ne voit QUE les projets de A (raw SQL)."""
    proj_a, proj_b = str(seeded["proj_a"]), str(seeded["proj_b"])
    conn = _connect(pg)
    try:
        cur = conn.cursor()
        cur.execute("SET app.current_studio_id = %s", (str(seeded["studio_a"]),))
        cur.execute("SELECT id FROM projects")
        a_ids = _ids(cur)
        # Propriété clé : ne JAMAIS voir le projet de l'autre tenant.
        assert proj_b not in a_ids, f"Studio A voit le projet de B: {a_ids}"
        assert proj_a in a_ids, f"Studio A doit voir son propre projet: {a_ids}"

        cur.execute("SET app.current_studio_id = %s", (str(seeded["studio_b"]),))
        cur.execute("SELECT id FROM projects")
        b_ids = _ids(cur)
        assert proj_a not in b_ids
        assert proj_b in b_ids
    finally:
        conn.close()


def test_rls_update_other_tenant_blocked(pg, seeded):
    """Studio A ne peut PAS modifier le projet de B (0 ligne affectée)."""
    conn = _connect(pg)
    try:
        cur = conn.cursor()
        cur.execute("SET app.current_studio_id = %s", (str(seeded["studio_a"]),))
        cur.execute(
            "UPDATE projects SET title = %s WHERE id = %s",
            ("HACK", seeded["proj_b"]),
        )
        assert cur.rowcount == 0, "RLS doit bloquer la MAJ cross-tenant"
        conn.commit()
    finally:
        conn.close()

    # Vérification : le projet B est intact (titre inchangé)
    admin = _superuser_connect(pg)
    try:
        cur = admin.cursor()
        cur.execute("SELECT title FROM projects WHERE id = %s", (seeded["proj_b"],))
        assert cur.fetchone()[0] == "Projet B"
    finally:
        admin.close()


def test_rls_delete_other_tenant_blocked(pg, seeded):
    """Studio A ne peut PAS supprimer le projet de B (0 ligne affectée)."""
    conn = _connect(pg)
    try:
        cur = conn.cursor()
        cur.execute("SET app.current_studio_id = %s", (str(seeded["studio_a"]),))
        cur.execute("DELETE FROM projects WHERE id = %s", (seeded["proj_b"],))
        assert cur.rowcount == 0, "RLS doit bloquer la suppression cross-tenant"
        conn.commit()
    finally:
        conn.close()

    admin = _superuser_connect(pg)
    try:
        cur = admin.cursor()
        cur.execute("SELECT count(*) FROM projects WHERE id = %s", (seeded["proj_b"],))
        assert cur.fetchone()[0] == 1, "Le projet B doit toujours exister"
    finally:
        admin.close()


def test_rls_insert_wrong_tenant_blocked(pg, seeded):
    """Studio A ne peut PAS insérer une ligne au nom de B (WITH CHECK)."""
    conn = _connect(pg)
    try:
        cur = conn.cursor()
        cur.execute("SET app.current_studio_id = %s", (str(seeded["studio_a"]),))
        new_id = uuid.uuid4()
        # La politique WITH CHECK rejette l'insertion cross-tenant → erreur SQL.
        with pytest.raises(psycopg2.Error):
            cur.execute(
                "INSERT INTO projects (id, studio_id, title, status) VALUES (%s,%s,%s,'Cree')",
                (new_id, seeded["studio_b"], "Intrus"),
            )
        conn.rollback()
    finally:
        conn.close()


def test_rls_insert_own_tenant_allowed(pg, seeded):
    """Studio A peut insérer une ligne pour son propre studio (rollback pour ne pas polluer)."""
    conn = _connect(pg)
    try:
        cur = conn.cursor()
        cur.execute("SET app.current_studio_id = %s", (str(seeded["studio_a"]),))
        new_id = uuid.uuid4()
        cur.execute(
            "INSERT INTO projects (id, studio_id, title, status) VALUES (%s,%s,%s,'Cree')",
            (new_id, seeded["studio_a"], "Nouveau projet A"),
        )
        conn.rollback()  # insert autorisé (pas d'exception) → on annule pour isoler les autres tests
    finally:
        conn.close()


def test_rls_media_isolated_via_projects_join(pg, seeded):
    """media_assets (sans studio_id) est isolé via la jointure sur projects."""
    media_a, media_b = str(seeded["media_a"]), str(seeded["media_b"])
    conn = _connect(pg)
    try:
        cur = conn.cursor()
        cur.execute("SET app.current_studio_id = %s", (str(seeded["studio_a"]),))
        cur.execute("SELECT id FROM media_assets")
        ids = _ids(cur)
        assert media_b not in ids, f"Studio A voit le média de B: {ids}"
        assert media_a in ids
    finally:
        conn.close()


def test_rls_no_context_sees_nothing(pg, seeded):
    """Sans contexte tenant positionné, aucune ligne tenant-scopée n'est visible."""
    conn = _connect(pg)
    try:
        cur = conn.cursor()
        # Pas de SET app.current_studio_id
        cur.execute("SELECT count(*) FROM projects")
        assert cur.fetchone()[0] == 0, "Sans contexte tenant, RLS doit tout masquer"
    finally:
        conn.close()


def test_rls_two_connections_concurrent_isolation(pg, seeded):
    """Deux connexions simultanées aux contextes distincts s'isolent mutuellement."""
    proj_a, proj_b = str(seeded["proj_a"]), str(seeded["proj_b"])
    conn_a = _connect(pg)
    conn_b = _connect(pg)
    try:
        ca, cb = conn_a.cursor(), conn_b.cursor()
        ca.execute("SET app.current_studio_id = %s", (str(seeded["studio_a"]),))
        cb.execute("SET app.current_studio_id = %s", (str(seeded["studio_b"]),))

        ca.execute("SELECT id FROM projects")
        a_ids = _ids(ca)
        cb.execute("SELECT id FROM projects")
        b_ids = _ids(cb)

        # Aucune fuite : chaque tenant ne voit JAMAIS le projet de l'autre.
        assert proj_b not in a_ids and proj_a in a_ids
        assert proj_a not in b_ids and proj_b in b_ids
        assert not (a_ids & b_ids), "Aucun chevauchement entre les deux tenants"
    finally:
        conn_a.close()
        conn_b.close()
