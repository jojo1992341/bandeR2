"""
Jeu de données de référence (fixtures) pour le développement et la recette (§9.7 CDC).

Ce module est **versionné** avec le schéma : il correspond à l'état `head` des
migrations Alembic et est maintenu en parallèle de l'évolution du schéma.

Utilisation :
    from app.fixtures.seed import load_fixtures, clear_fixtures
    load_fixtures(session)      # charge le jeu de données
    clear_fixtures(session)     # purge le jeu de données

Les fixtures contournent RLS (chargement en tant que superuser / admin DB).
"""

from app.fixtures.seed import RECETTE_PASSWORD, clear_fixtures, load_fixtures

__all__ = ["load_fixtures", "clear_fixtures", "RECETTE_PASSWORD"]
