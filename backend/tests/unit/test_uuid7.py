"""
Tests unitaires UUID v7 (§9.5 CDC) — G-010.

Vérifie que les nouvelles clés primaires sont des UUID v7 ordonnés
temporellement (RFC 9562), propriété clé pour la performance d'indexation
B-Tree par rapport aux UUID v4 aléatoires.
"""

from __future__ import annotations

import time
import uuid

import pytest

from app.core.uuid7 import uuid7


def test_uuid7_version_is_7():
    u = uuid7()
    assert isinstance(u, uuid.UUID)
    assert u.version == 7


def test_uuid7_are_unique():
    ids = {uuid7() for _ in range(1000)}
    assert len(ids) == 1000, "1000 UUID v7 générés doivent être uniques"


def test_uuid7_temporal_order_cross_millisecond():
    """Des UUID générés à des instants distincts respectent l'ordre chronologique."""
    base = 1_700_000_000_000  # ms
    older = uuid7(base)
    mid = uuid7(base + 7_000)
    newer = uuid7(base + 60_000)

    # Ordre lexicographique (chaîne) == ordre chronologique
    assert str(older) < str(mid) < str(newer)
    # Ordre numérique aussi
    assert older.int < mid.int < newer.int
    # Générés à timestamps croissants → la liste est déjà triée
    seq = [uuid7(base + i * 5_000) for i in range(10)]
    assert [str(u) for u in seq] == sorted(str(u) for u in seq)
    # L'ordre suit toujours le timestamp, même si créé hors séquence
    out_of_order = [uuid7(base + 5_000), uuid7(base), uuid7(base + 100_000)]
    by_ts = sorted(out_of_order, key=lambda _: str(_))
    assert str(uuid7(base)) < str(uuid7(base + 5_000)) < str(uuid7(base + 100_000))


def test_uuid7_monotonic_within_same_millisecond():
    """Plusieurs UUID générés durant la même ms restent ordonnés (compteur monotone)."""
    ts = 1_700_000_000_000
    ids = [uuid7(ts) for _ in range(50)]
    for u in ids:
        assert u.version == 7
    # Tous strictement croissants dans l'ordre de génération
    str_ids = [str(u) for u in ids]
    assert str_ids == sorted(str_ids), "UUID same-ms doivent être monotones croissants"
    assert len(set(str_ids)) == 50


def test_uuid7_temporal_order_on_real_clock():
    """Sur l'horloge réelle, deux UUID éloignés dans le temps sont ordonnés."""
    a = uuid7()
    time.sleep(0.005)  # 5 ms
    b = uuid7()
    assert a.version == 7 and b.version == 7
    assert str(a) < str(b)


def test_models_use_uuid7_as_pk_default():
    """Les nouvelles clés des entités principales utilisent uuid7 (§9.5)."""
    from app.models import Replica, RythmoBand, Word, Project, Speaker

    for model in (Replica, RythmoBand, Word, Project, Speaker):
        default = model.__table__.columns["id"].default
        assert default is not None, f"{model.__name__}.id doit avoir une valeur par défaut"
        # Valeur par défaut Python (CallableColumnDefault) ciblant uuid7.
        arg = getattr(default, "arg", None)
        assert arg is not None, f"{model.__name__}.id default doit être un callable"
        assert getattr(arg, "__name__", "") == "uuid7", (
            f"{model.__name__}.id doit utiliser uuid7, trouvé {arg!r}"
        )


def test_models_generate_uuid7_on_insert():
    """End-to-end : l'insertion d'une réplique produit bien un UUID v7."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import Base, Replica, Studio, Project, MediaAsset

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        st = Studio(name="S", plan="pro")
        s.add(st)
        s.flush()
        p = Project(studio_id=st.id, title="P")
        s.add(p)
        s.flush()
        m = MediaAsset(project_id=p.id, storage_path="x", status="confirmed")
        s.add(m)
        s.flush()
        r = Replica(media_id=m.id, text="t")
        s.add(r)
        s.flush()
        assert r.id.version == 7
        assert st.id.version == 7
        assert p.id.version == 7
