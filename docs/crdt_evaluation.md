# Évaluation Architecture CRDT §16.4 — Édition Collaborative

**Contexte :** Actuellement, l'édition collaborative repose sur un verrouillage optimiste par réplique (champ `version`, 409 Conflict si version stale). Cette approche est simple et suffisante pour le volume actuel où les répliques sont rarement éditées simultanément (cf. §16.4). Pour la V2, où le volume et le nombre d'éditeurs concurrents augmentera (studios Enterprise, 50+ projets, édition temps réel), une édition caractère par caractère sans perte est requise.

## 1. Objectif

Permettre à deux (ou N) utilisateurs d'éditer le même `Replica.text` simultanément, caractère par caractère, et garantir la **convergence** (tous les réplicas finissent avec le même texte) **sans perte de données**, là où le volume le justifie.

Condition d'achèvement : test de convergence démontrant que deux éditions concurrentes sur la même réplique convergent vers un état cohérent sans perte.

## 2. Alternatives Évaluées

### 2.1 Verrouillage Optimiste (actuel, §16.4 MVP)

**Principe :** Chaque `Replica` a un compteur `version`. Le client envoie `PATCH /replicas/{id} {text, version}`. Si `version != current_version` en DB → 409 Conflict. Le client doit recharger et rejouer.

**Avantages :**
- Simple, pas d'état supplémentaire
- Fonctionne avec l'existant (undo/redo `Command`, WebSocket `replica_lock_ws`)
- Suffisant pour volume faible (1 éditeur à la fois par réplique)

**Inconvénients :**
- 409 fréquent dès que 2 éditeurs tapent en même temps → perte de temps, reprise manuelle
- Pas de fusion automatique : le dernier écrase le premier si on force l'écriture
- Expérience utilisateur dégradée en cas de forte concurrence (ex: 5 adaptateurs sur un même épisode)

**Complexité :** O(1)

### 2.2 Operational Transformation (OT)

**Principe :** Serveur central transforme les opérations concurrentes (`insert(pos, char)`, `delete(pos)`) pour les rendre commutatives. Ex: Google Docs, ShareJS.

**Avantages :**
- Historique, intention préservée, très mature

**Inconvénients :**
- Nécessite un serveur central qui connaît l'ordre total des opérations et applique des fonctions de transformation `IT(p,q)` pour chaque paire d'opérations → complexité O(n²), difficile à implémenter correctement (nécessite de prouver les propriétés TP1/TP2)
- Difficile à décentraliser, point de défaillance unique
- Doit gérer l'historique des opérations pour la transformation

**Complexité :** O(n) par opération, mais implémentation complexe et erreurs subtiles.

### 2.3 CRDT (Conflict-free Replicated Data Type) — Choisi pour V2

**Principe :** Type de données répliqué qui garantit la convergence sans coordination, par commutativité, associativité et idempotence. Chaque caractère a un identifiant unique `(site, counter)` et une position `pos` (Logoot/RGA). Les opérations sont **commutatives** : `apply(A) ∘ apply(B) = apply(B) ∘ apply(A)`.

**Choix : RGA / Logoot-like** (Replicated Growable Array) avec position `pos: List[int]` et tie-breaker `siteId`.

- **Caractère** : `{char, id: {site, counter}, pos: [int], visible: bool}`
- **Insert** : génère `pos` entre `left.pos` et `right.pos` via `_generate_pos_between` (si `left+1 < right` → milieu, sinon `left + [siteHash]`). Tri par `(pos, site, counter)` donne un ordre total déterministe.
- **Delete** : marque `visible=false` (tombstone), ne supprime jamais l'identifiant → convergence.
- **Version Vector** : `{site: counter}` pour la causalité, permet de détecter les opérations concurrentes vs causales.

**Avantages :**
- Décentralisé, pas de serveur central pour la transformation
- Opérations commutatives → convergence garantie sans 409
- Idéal pour volume élevé et édition P2P / offline
- Simple à raisonner : chaque site génère des IDs uniques, l'ordre est déterministe

**Inconvénients :**
- État plus volumineux (tombstones, pos)
- Nécessite un GC pour les tombstones (non critique pour nos tailles de réplique < 500 chars)
- Un peu plus de stockage JSON (mais négligeable vs vidéo)

**Complexité :** O(log n) pour l'insertion (recherche des voisins) + O(n log n) pour le tri, acceptable pour n < 1000.

**Décision :** CRDT RGA/Logoot retenu pour V2, avec **feature flag** `FEATURE_CRDT` et **seuil de volume** (ex: >10 répliques ou plan `pro/enterprise` ou titre contient `crdt`). Fallback vers verrouillage optimiste si désactivé ou volume faible.

## 3. Architecture Implémentée

### Backend

- **Modèle** `ReplicaCrdtState` (`replica_id PK`, `characters JSON`, `version_vector JSON`, `clock`, `text` matérialisé) + `ReplicaCrdtOperation` (journal `site_id, counter, op_type, position, char, pos_id, version_vector, timestamp`)
- **Service** `CrdtService` (`TextCRDT` Python) : `get_or_create_state`, `apply_operation`, `get_text`, `merge_states`, `should_use_crdt` (flag + volume)
- **API** `POST /replicas/{id}/crdt/{init,state,operation,sync,bulk,enabled}` (cf. `app/api/v1/crdt.py`)
- **Feature Flag** `config.py` : `FEATURE_CRDT` / `ENABLE_CRDT`, `is_feature_enabled("crdt")`, `CrdtService.is_enabled()`
- **Migration** `y6z7a8b9c0d1` : création des deux tables

### Frontend

- **Module** `src/crdt/text_crdt.js` : `TextCRDT` JS (même algo que Python, compatible), `hashSite`, `_generatePosBetween`, `insert/delete/getText/merge`
- **Store** `RythmoStore` : pourrait déléguer à CRDT si `featureEnabled`, sinon garde `Command` + `version`
- **Éditeur** `replica_editor.js` : pourrait envoyer `POST /crdt/operation` au lieu de `PATCH` si CRDT activé (non bloquant pour le test de convergence)

### Persistance

Le texte matérialisé `Replica.text` est toujours mis à jour depuis `CrdtState.text` pour compatibilité avec l'existant (recherche, export, timeline). Le CRDT est la source de vérité quand activé.

## 4. Test de Convergence

**Scénario :** Texte initial `"Hello"`, deux sites concurrents insèrent à la même position logique 2 (`"He|llo"`):
- Site A : `insert(2, "X")` → `"HeXllo"` (pos ` [1,430]`)
- Site B : `insert(2, "Y")` → `"HeYllo"` (pos `[1,293]`)

Sans CRDT (optimistic lock) : le second `PATCH` avec `version` stale → **409 Conflict**, l'un des deux perd son édition.

Avec CRDT : les deux opérations ont des `pos` distincts (`[1,293]` vs `[1,430]`) avec tie-breaker `siteId`. Quel que soit l'ordre d'application (`A puis B` ou `B puis A`), le tri `(pos, site, counter)` donne **toujours** `"HeYXllo"` (Y avant X car `site-B (293) < site-A (430)`), longueur 7, sans perte. Idem pour `delete` + `insert`.

Le test `test_crdt_convergence` vérifie :
- `siteA.getText() == siteB.getText()` après échange
- `"X" in text and "Y" in text`
- `len == len(initial) + 2`
- Idem via `CrdtService` DB et via `POST /crdt/operation` API (deux ordres → même final)

**Résultat : convergence démontrée, sans perte, ordre déterministe.**

## 5. Déploiement Progressif

- `FEATURE_CRDT=0` par défaut → verrouillage optimiste (comportement actuel, 0 impact)
- `FEATURE_CRDT=1` ou `project.title` contient `crdt` ou `volume > 10` → CRDT activé pour ce projet/réplique
- Permet un déploiement progressif studio par studio, comme pour `lip_sync` (§19.3)

## 6. Limitations et Suite

- GC des tombstones non implémenté (OK pour nos volumes)
- Pas encore de WebSocket CRDT temps réel (actuellement via polling `POST /crdt/sync`), à brancher sur `replica_lock_ws` en V2
- Conflits de `typo_codes` / `speaker_id` restent en verrouillage optimiste (seul `text` est en CRDT pour l'instant) — extension possible

## 7. Références

- Shapiro et al., "Conflict-free Replicated Data Types", 2011
- Kleppmann, "Designing Data-Intensive Applications", Ch.5
- Yjs (https://yjs.dev), Automerge
