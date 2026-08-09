# Règles de migration & gouvernance de schéma (CDC §9.7)

Toute évolution du schéma passe par une migration Alembic versionnée, revue en
pull request. Les migrations doivent rester **rétro-compatibles** pour permettre
des déploiements sans interruption de service (expand/contract).

## 1. Principes obligatoires

| Règle | Détail | Vérifiée par |
|-------|--------|-------------|
| Une migration = un fichier dans `alembic/versions/` | `revision` + `down_revision` chaînés | `test_linear_single_root_single_head` |
| `upgrade()` **et** `downgrade()` | Toute migration doit être réversible | `test_every_migration_has_upgrade_and_downgrade` |
| `revision` ≤ 32 caractères | `alembic_version.version_num` est `VARCHAR(32)` | `test_revision_ids_fit_alembic_version_column` |
| Pas d'identifiant en doublon | Une seule racine, une seule tête | `test_no_duplicate_revision_ids` |
| Schéma migré = modèles | Aucune table/colonne modèle absente après `upgrade head` | `test_migrated_schema_matches_models` |
| Chaîne réversible | `base → head → base → head` sans erreur | `test_full_chain_reversible_schema_only` |

## 2. Patron expand/contract (déploiement sans interruption)

Une migration rétro-compatible se déroule en **deux déploiements successifs** :

1. **Expand** (migration additive, rétro-compatible avec le code précédent) :
   - ajouter une table / colonne **nullable** ou avec `server_default` ;
   - ajouter un index (`CREATE INDEX CONCURRENTLY` en production si possible) ;
   - **ne jamais** supprimer/renommer une colonne utilisée par le code en production.

2. **Déploiement du code** qui utilise la nouvelle structure.

3. **Contract** (migration de nettoyage, après bascule complète du code) :
   - rendre une colonne `NOT NULL` (après backfill des lignes existantes) ;
   - supprimer une colonne/une table obsolète ;
   - supprimer un ancien index.

**Règles pratiques :**
- Préférer `ADD COLUMN ... NULL` ou avec `DEFAULT` ; n'imposer `NOT NULL` qu'au
  contract (après backfill).
- Ne jamais renommer une colonne en une étape : ajouter la nouvelle, doubler
  l'écriture, migrer les lectures, puis supprimer l'ancienne au contract.
- Pour les index en production, utiliser `CREATE INDEX CONCURRENTLY` (hors
  transaction) — adapter `op.execute(...)` car Alembic l'inclut par défaut dans
  une transaction.
- Toute opération destructive (`DROP COLUMN/TABLE`, `ALTER TYPE` non additif)
  doit vivre dans une migration de **contract** distincte, documentée.

## 3. Idempotence des index

Une colonne déclarée avec `index=True` dans `op.create_table(...)` génère
automatiquement son index `ix_<table>_<col>`. **Ne pas** rajouter un
`op.create_index(...)` explicite pour la même colonne (échec `duplicate table`).
À l'inverse, un index composite ou nommé explicitement n'a pas de
`index=True` sur la colonne.

## 4. UUID v7 et clés primaires (§9.5)

Les nouvelles PK utilisent `uuid7` (côté applicatif) — ne pas définir de
`server_default` SQL générique en migration (l'application fournit l'UUID).
Les UUID v4 existants cohabitent sans migration de données.

## 5. Row-Level Security (§9.6)

Les migrations créant une table tenant-scopée (`studio_id`) doivent être
suivies (dans la même migration ou une migrée avant mise en production) d'une
politique RLS. Voir `004_enable_rls.apply_rls_ddl`.

## 6. Validation CI

Le job `migrations_and_fixtures_postgres` démarre un PostgreSQL 16 embarqué
(`pgserver`), monte la chaîne depuis une base vide, charge les fixtures, effectue
un downgrade/upgrade supporté et valide l'intégrité — voir
`backend/tests/integration/test_migrations_and_fixtures.py`.

## 7. Fixtures versionnées (§9.7)

`backend/app/fixtures/seed.py` maintient un jeu de données de référence pour le
développement et la recette. Il est **versionné avec le schéma** : toute
migration ajoutant une entité doit étendre les fixtures en conséquence.
