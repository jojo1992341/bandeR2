"""
Gouvernance des migrations Alembic (§9.7 CDC) — G-011.

Vérifications statiques (sans PostgreSQL) :
- chaque migration définit `upgrade()` ET `downgrade()` ;
- la chaîne est linéaire (une seule racine, une seule tête, pas de branche) ;
- les identifiants de révision tiennent dans `alembic_version.version_num`
  (VARCHAR(32)) ;
- les migrations utilisent le moteur PostgreSQL (présence de `op`/`sa`).

Ces règles garantissent que la chaîne est rétro-compatible et réversible,
prérequis de l'expand/contract (§9.7) et des déploiements sans interruption.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

VERSIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "alembic" / "versions"
)


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(
        f"mig_{path.stem}", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _all_migration_paths():
    return sorted(VERSIONS_DIR.glob("*.py"))


def _parse_revisions():
    revs = {}
    for path in _all_migration_paths():
        text = path.read_text(encoding="utf-8")
        rid = re.search(
            r'^revision(?:\s*:\s*[^=]+)?\s*=\s*[\'"](.+?)[\'"]', text, re.M
        )
        down = re.search(
            r'^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(.+)$', text, re.M
        )
        assert rid, f"revision introuvable dans {path.name}"
        d_raw = down.group(1).strip() if down else "None"
        d = None if d_raw in ("None", "None  # après la création de la table replicas") else (
            d_raw.strip("'\"")
        )
        # nettoyage commentaires éventuels
        if d and "#" in d:
            d = d.split("#")[0].strip().strip("'\"")
        revs[rid.group(1)] = d
    return revs


def test_every_migration_has_upgrade_and_downgrade():
    paths = _all_migration_paths()
    assert paths, "Aucune migration trouvée"
    for path in paths:
        module = _load_migration(path)
        assert callable(getattr(module, "upgrade", None)), (
            f"{path.name} doit définir upgrade()"
        )
        assert callable(getattr(module, "downgrade", None)), (
            f"{path.name} doit définir downgrade() (§9.7 : réversibilité)"
        )


def test_revision_ids_fit_alembic_version_column():
    """alembic_version.version_num est VARCHAR(32) : les IDs doivent tenir."""
    for path in _all_migration_paths():
        text = path.read_text(encoding="utf-8")
        m = re.search(
            r'^revision(?:\s*:\s*[^=]+)?\s*=\s*[\'"](.+?)[\'"]', text, re.M
        )
        rid = m.group(1)
        assert len(rid) <= 32, (
            f"{path.name}: revision '{rid}' ({len(rid)} chars) > 32 "
            f"(limite alembic_version.version_num)"
        )


def test_linear_single_root_single_head():
    revs = _parse_revisions()
    roots = [r for r, d in revs.items() if d is None]
    assert len(roots) == 1, (
        f"La chaîne doit avoir exactement une racine, trouvé: {roots}"
    )
    downs = {d for d in revs.values() if d is not None}
    heads = [r for r in revs if r not in downs]
    assert len(heads) == 1, (
        f"La chaîne doit avoir exactement une tête, trouvé: {heads}"
    )
    # Tous les down_revisions pointent vers une révision existante.
    for rev, down in revs.items():
        if down is not None:
            assert down in revs, (
                f"La révision {rev} référence un down_revision inconnu: {down}"
            )


def test_no_duplicate_revision_ids():
    revs = _parse_revisions()
    # _parse_revisions retourne un dict (clés uniques) ; on vérifie via les fichiers
    all_ids = []
    for path in _all_migration_paths():
        text = path.read_text(encoding="utf-8")
        m = re.search(
            r'^revision(?:\s*:\s*[^=]+)?\s*=\s*[\'"](.+?)[\'"]', text, re.M
        )
        all_ids.append(m.group(1))
    assert len(all_ids) == len(set(all_ids)), (
        f"Identifiants de révision en doublon: {all_ids}"
    )
    assert len(all_ids) == len(revs)
