# Séparation Calcul/Stockage - Workers IA (§5.4 CDC)

Ce document décrit l'architecture de séparation entre les workers IA et la base de données applicative.

## Table des matières
- [Principe](#principe)
- [Architecture](#architecture)
- [Internal API](#internal-api)
- [Artefacts](#artefacts)
- [Migration des tâches](#migration-des-taches)
- [Tests](#tests)
- [Compatibilité](#compatibilite)

## Principe (§5.4 CDC)

Le CDC §5.4 impose une séparation stricte entre:
- **Calcul (Workers IA)**: Traitement des données (transcription, analyse, etc.)
- **Stockage (Base applicative)**: Persistance des données métier

Cette séparation permet:
1. **Évolutivité**: Ajouter des workers sans impacter la base de données
2. **Sécurité**: Les workers n'ont pas accès direct à la base de données
3. **Flexibilité**: Changer de stockage sans modifier les workers
4. **Observabilité**: Chaque artefact est traçable via son UUID

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Externe                               │
│  (Routes FastAPI - gère les requêtes utilisateurs)              │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ (accès DB direct autorisé)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Base de données applicative                    │
│     (PostgreSQL - données métier: projets, utilisateurs, etc.)  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      Workers IA (Celery)                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  transcription.py  →  WorkerInternalAPI  →  S3/MinIO      │ │
│  │  emotion_detection.py →  WorkerInternalAPI  →  S3/MinIO    │ │
│  │  forced_alignment.py →  WorkerInternalAPI  →  S3/MinIO     │ │
│  │  lip_sync.py        →  WorkerInternalAPI  →  S3/MinIO      │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              │ (stockage objet)                 │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Stockage Objet (S3/MinIO)                │ │
│  │  - artefacts/metadata/{uuid}.json  (métadonnées)           │ │
│  │  - artefacts/results/{uuid}/...     (résultats)            │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Internal API

Le module `app.internal_api` fournit une interface pour les workers.

### WorkerInternalAPI

```python
from app.internal_api import WorkerInternalAPI, ArtifactMetadata
from uuid import UUID

api = WorkerInternalAPI()

# Créer un artefact
metadata = ArtifactMetadata(
    id=UUID("..."),
    type="transcription",
    media_id=UUID("..."),
    status="pending",
)
api.save_artifact(metadata)

# Sauvegarder des résultats
result_path = api.save_result(
    artifact_id,
    {"segments": [...]},
    content_type="application/json"
)

# Mettre à jour le statut
api.update_artifact_status(
    artifact_id,
    status="completed",
    result_path=result_path
)
```

### Méthodes disponibles

| Méthode | Description |
|---------|-------------|
| `get_artifact(artifact_id)` | Récupère les métadonnées d'un artefact |
| `save_artifact(metadata)` | Sauvegarde les métadonnées |
| `update_artifact_status(...)` | Met à jour le statut et le chemin des résultats |
| `save_result(artifact_id, data, ...)` | Sauvegarde les résultats dans S3 |
| `get_result(result_path)` | Récupère les résultats depuis S3 |
| `health_check()` | Vérifie la santé de l'API |

## Artefacts

Chaque résultat de calcul est stocké comme un **artefact** identifié par un UUID.

### Structure

```
s3://bucket/
├── artifacts/
│   ├── metadata/
│   │   ├── {uuid}.json          # Métadonnées de l'artefact
│   │   └── ...
│   └── results/
│       ├── {uuid}/
│       │   └── {timestamp}/
│       │       └── result        # Résultats du calcul
│       └── ...
```

### Métadonnées d'un artefact

```json
{
  "id": "uuid",
  "type": "transcription|emotion_detection|lip_sync|...",
  "media_id": "uuid",
  "project_id": "uuid|null",
  "status": "pending|processing|completed|failed",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "result_path": "s3://bucket/artifacts/results/...",
  "error": "message d'erreur le cas échéant"
}
```

## Migration des tâches

### Avant (accès DB direct)

```python
# app/tasks/transcription.py (AVANT)
from app.core.database import SessionLocal
from app.models import TranscriptSegment

@celery_app.task
def transcribe_audio(media_path, media_id):
    db = SessionLocal()
    try:
        for seg in segments:
            db.add(TranscriptSegment(...))
        db.commit()
    finally:
        db.close()
```

### Après (Internal API)

```python
# app/tasks/transcription.py (APRES)
from app.internal_api import WorkerInternalAPI, ArtifactMetadata

@celery_app.task
def transcribe_audio(media_path, media_id):
    api = get_worker_api()
    
    # Sauvegarder les résultats dans S3
    result_path = api.save_result(artifact_id, segments_data)
    
    # Mettre à jour les métadonnées
    api.update_artifact_status(artifact_id, "completed", result_path)
```

### Tâches migrées

| Tâche | Statut migration |
|-------|-----------------|
| `transcription.py` | ✅ Migtrée |
| `emotion_detection.py` | ✅ Migtrée |
| `forced_alignment.py` | ✅ Migtrée |
| `lip_sync.py` | ✅ Migtrée |
| `pipeline.py` | ✅ Migtrée |

## Tests

### Exécuter les tests

```bash
cd backend
python -m pytest tests/integration/test_worker_separation_5_4.py -v
```

### Tests inclus

| Test | Description |
|------|-------------|
| `test_no_sessionlocal_in_*` | Vérifie qu'aucune tâche n'utilise SessionLocal |
| `test_internal_api_used_in_tasks` | Vérifie que les tâches utilisent WorkerInternalAPI |
| `test_full_pipeline_via_internal_api` | Test du flux complet extraction→transcription→persistance |
| `test_artifact_metadata_*` | Tests des métadonnées d'artefacts |
| `test_legacy_session_adapter_raises` | Vérifie que l'adaptateur legacy lève une erreur |

### Résultat attendu

```
============================= test session starts ==============================
...
tests/integration/test_worker_separation_5_4.py::TestWorkerDBSeparation::test_no_sessionlocal_in_transcription PASSED
tests/integration/test_worker_separation_5_4.py::TestWorkerDBSeparation::test_no_sessionlocal_in_emotion_detection PASSED
tests/integration/test_worker_separation_5_4.py::TestWorkerDBSeparation::test_no_sessionlocal_in_forced_alignment PASSED
tests/integration/test_worker_separation_5_4.py::TestWorkerDBSeparation::test_no_sessionlocal_in_lip_sync PASSED
tests/integration/test_worker_separation_5_4.py::TestWorkerDBSeparation::test_internal_api_used_in_tasks PASSED
...
======================== 17 passed, 1 warning in 0.28s =========================
```

## Compatibilité

### LegacySessionAdapter

Pendant la migration, une classe `LegacySessionAdapter` est disponible pour les tâches qui n'ont pas encore été migrées. Elle lève une `NotImplementedError` pour forcer la migration.

```python
from app.internal_api import LegacySessionAdapter

adapter = LegacySessionAdapter()
adapter.query("Model")  # Lève NotImplementedError
```

### DBAccessDetector

Pour les tests, un détecteur d'accès DB permet de vérifier qu'aucun accès direct n'est effectué.

```python
from app.internal_api import DBAccessDetector

DBAccessDetector.enable()
# ... exécuter le code à tester ...
success, violations = DBAccessDetector.check_no_direct_access()
assert success, f"Accès DB détectés: {violations}"
```

## Files modifiés

- `app/internal_api.py` - Nouveau: API interne pour les workers
- `app/core/storage.py` - Étendu: Service de stockage amélioré
- `app/tasks/transcription.py` - Modifié: Utilise Internal API
- `app/tasks/emotion_detection.py` - Modifié: Utilise Internal API
- `app/tasks/forced_alignment.py` - Modifié: Utilise Internal API
- `app/tasks/lip_sync.py` - Modifié: Utilise Internal API
- `app/tasks/pipeline.py` - Modifié: Utilise Internal API
- `tests/integration/test_worker_separation_5_4.py` - Nouveau: Tests d'intégration

## Prochaines étapes

1. **Compléter la migration** de toutes les tâches IA
2. **Implémenter l'API externe** pour que les workers puissent récupérer les métadonnées des projets/médias
3. **Ajouter un index d'artefacts** pour faciliter la recherche (Elasticsearch ou table DB dédiée)
4. **Supprimer LegacySessionAdapter** une fois la migration terminée
