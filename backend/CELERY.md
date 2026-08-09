# Application Celery - RythmoAI Backend (§6.4, §13.1, §18.3 CDC)

Ce document décrit l'application Celery centralisée pour le backend RythmoAI.

## Table des matières
- [Vue d'ensemble](#vue-densemble)
- [Architecture](#architecture)
- [Installation](#installation)
- [Utilisation](#utilisation)
- [Tâches](#taches)
- [Configuration](#configuration)
- [Tests](#tests)
- [Dépannage](#depannage)

## Vue d'ensemble

L'application Celery a été refactorisée pour utiliser une **instance unique centralisée** au lieu d'une instance par module.

**Avant:**
```
app/tasks/pipeline.py     → celery_app = Celery("rythmoai", ...)
app/tasks/transcription.py → celery_app = Celery("rythmoai", ...)
app/tasks/export.py       → celery_app = Celery("rythmoai", ...)
...
```

**Après:**
```
app/celery_app.py         → celery_app = Celery("rythmoai")  # Unique
app/tasks/*.py            → from app.celery_app import celery_app
```

## Architecture

```
backend/
├── app/
│   ├── celery_app.py      # Application Celery unique (factory + config)
│   └── tasks/
│       ├── __init__.py    # Ré-exporte celery_app + imports modules
│       ├── pipeline.py    # Tâches pipeline (extract, transcribe, etc.)
│       ├── transcription.py
│       ├── export.py
│       ├── normalize_audio.py
│       ├── forced_alignment.py
│       ├── diarize_speakers.py
│       ├── prosody_analysis.py
│       ├── generate_rythmo.py
│       ├── audio_extraction.py
│       ├── lip_sync.py
│       ├── source_separation.py
│       ├── emotion_detection.py
│       └── ... (autres tâches)
├── scripts/
│   └── list_tasks.py      # Script pour lister les tâches ( Alternative à celery inspect)
└── test_celery.py         # Script de test Celery
```

## Installation

### Prérequis

- Python 3.10+
- Redis ou Memurai (broker et backend)

### Installer Redis

**Option 1: Redis via apt (Linux)**
```bash
sudo apt-get update
sudo apt-get install redis-server
redis-server --daemonize yes
```

**Option 2: Redis via Docker**
```bash
docker run -d -p 6379:6379 --name redis redis:alpine
```

**Option 3: Memurai (compatible Redis, Windows/Linux)**
```bash
# Télécharger depuis https://memurai.com/
# Ou utiliser le package npm (si disponible)
npm install -g memurai
```

**Option 4: Redis en mode test (sans serveur)**
```bash
export CELERY_TEST_MODE=true
# Les tâches s'exécuteront de manière synchrone (eager)
```

### Installer les dépendances Python

```bash
cd backend
pip install -r requirements.txt
# Celery et redis sont inclus dans requirements.txt
```

## Utilisation

### Démarrer un worker

```bash
cd backend

# Worker par défaut (queue: celery)
celery -A app.celery_app worker --loglevel=info

# Worker avec queues spécifiques
celery -A app.celery_app worker -Q celery,exports,ia --loglevel=info

# Worker avec concurrency ajusté
celery -A app.celery_app worker --concurrency=4 --loglevel=info

# Worker en arrière-plan (avec supervision)
celery -A app.celery_app worker --daemonize
```

### Inspector les tâches

```bash
# Liste des tâches enregistrées (équivalent à celery inspect registered)
celery -A app.celery_app inspect registered

# Alternative sans serveur Redis (mode eager)
python scripts/list_tasks.py

# Alternative avec Redis
python test_celery.py
```

### Envoyer une tâche

```python
from app.celery_app import celery_app, health_check, ping, add

# Tâche de santé
result = health_check.delay()
print(result.get())  #Attend la completion

# Tâche ping
result = ping.delay()
print(result.get())  # "pong"

# Tâche add
result = add.delay(2, 3)
print(result.get())  # 5
```

### Envoyer une tâche pipeline

```python
from app.tasks.pipeline import pipeline_extract_normalize

# Lancer le pipeline d'extraction
result = pipeline_extract_normalize.delay(
    media_path="/path/to/video.mp4",
    media_id="uuid-here",
    pipeline_options={
        "enable_source_separation": True,
        "source_separation_backend": "spectral"
    }
)
```

## Tâches

### Tâches de santé (3)
| Tâche | Description |
|-------|-------------|
| `app.tasks.health_check` | Vérifie que Celery fonctionne |
| `app.tasks.ping` | Test de connectivité (retourne "pong") |
| `app.tasks.add` | Additionneur test (x + y) |

### Tâches Pipeline (6)
| Tâche | Description |
|-------|-------------|
| `pipeline_extract_normalize` | Extraction + normalisation audio EBU R128 |
| `pipeline_transcribe_diarize` | Transcription Whisper + diarisation |
| `pipeline_generate_rythmo` | Génération bande rythmo |
| `pipeline_detect_lip_sync` | Détection synchronisation labiale |
| `pipeline_detect_emotions` | Détection émotions |
| `notify_completion` | Mise à jour statut + notification |

### Tâches Export (4)
| Tâche | Description |
|-------|-------------|
| `export.export_project` | Export projet MP4 |
| `export.export_to_srt` | Export sous-titres SRT |
| `export.export_to_vtt` | Export sous-titres VTT |
| `export_project.export_project_legacy` | Export legacy (compatibilité) |

### Tâches IA/Traitement (18)
| Tâche | Module | Description |
|-------|--------|-------------|
| `transcription.transcribe_audio` | Whisper | Transcription audio |
| `diarize_speakers.diarize_speakers` | Pyannote | Diarisation locuteurs |
| `emotion_detection.detect_emotions` | Double analyse | Détection émotions |
| `lip_sync.detect_lip_sync` | FaceMesh | Détection ouverture labiale |
| `source_separation.separate_sources` | Spectral/Demucs | Séparation sources |
| `forced_alignment.forced_alignment` | Whisper | Alignement forcé |
| `normalize_audio.normalize_audio` | FFmpeg | Normalisation EBU R128 |
| `audio_extraction.extract_audio` | FFmpeg | Extraction pistes audio |
| `generate_rythmo.generate_rythmo_band` | RythmoEngine | Génération rythmo |
| `prosody_analysis.prosody_analysis` | - | Analyse prosodique |
| `prosody_analysis.analyze_prosody` | - | Alias prosodie |
| ...et d'autres | | |

**Total: 30 tâches enregistrées**

## Configuration

### Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | URL du broker Redis |
| `CELERY_TEST_MODE` | `false` | Active le mode eager (sans broker) |
| `task_always_eager` | `false` (production) | Exécution synchrone |

### Configuration Celery (dans app/celery_app.py)

```python
config = {
    # Broker et backend
    "broker_url": "redis://localhost:6379/0",
    "result_backend": "redis://localhost:6379/0",
    
    # Sérialisation
    "task_serializer": "json",
    "result_serializer": "json",
    
    # Résilience (§6.4)
    "task_acks_late": True,
    "task_reject_on_worker_lost": True,
    "task_max_retries": 3,
    "task_default_retry_delay": 10,
    
    # Workers (§18.3)
    "worker_prefetch_multiplier": 1,
    "worker_max_tasks_per_child": 1000,
    "worker_max_memory_per_child": 500000,  # 500MB
    "worker_concurrency": 2,
    
    # Queues
    "task_routes": {
        "app.tasks.pipeline.*": {"queue": "celery"},
        "app.tasks.dlq.*": {"queue": "dead_letter"},
        "app.tasks.export.*": {"queue": "exports"},
        "app.tasks.ia.*": {"queue": "ia"},
    },
}
```

### Queues disponibles

| Queue | Tâches |
|-------|--------|
| `celery` | Pipeline, traitement IA, export |
| `dead_letter` | Tâches en échec après retries |
| `exports` | Tâches d'export (réservé) |
| `ia` | Tâches IA lourdes (réservé) |

## Tests

### Test sans Redis (mode eager)

```bash
cd backend
CELERY_TEST_MODE=true python test_celery.py
```

Cela exécute les tâches de manière synchrone sans nécessiter de serveur Redis.

### Test avec Redis

```bash
# 1. Démarrer Redis
redis-server --daemonize yes

# 2. Lancer un worker
celery -A app.celery_app worker --loglevel=info &

# 3. Tester
python test_celery.py

# 4. Arrêter le worker
pkill -f "celery worker"
```

### Lancer les tests pytest

```bash
cd backend
pytest tests/ -v
```

## Dépannage

### Erreur: "Could not connect to the message broker"

```bash
# Vérifier que Redis est démarré
redis-cli ping
# Doit retourner: PONG

# Si Redis n'est pas disponible, utiliser le mode test
export CELERY_TEST_MODE=true
python test_celery.py
```

### Erreur: "Connection refused" sur le port 6379

```bash
# Vérifier si Redis écoute
netstat -tlnp | grep 6379
# ou
ss -tlnp | grep 6379

# Démarrer Redis
redis-server --daemonize yes
```

### Tâches non enregistrées

```bash
# Vérifier que les modules sont importés
python -c "import app.tasks.pipeline; import app.tasks.transcription; ..."

# Lister les tâches
python scripts/list_tasks.py
```

### Worker ne traite pas les tâches

```bash
# Vérifier les logs du worker
celery -A app.celery_app worker --loglevel=debug

# Vérifier les tâches en attente
celery -A app.celery_app inspect scheduled

# Vérifier les tâches en cours
celery -A app.celery_app inspect active
```

### Memory leak sur le worker

```bash
# Réduire worker_max_tasks_per_child
# (déjà configuré à 1000 dans celery_app.py)

# Ou redémarrer le worker périodiquement
celery -A app.celery_app worker --max-tasks-per-child=100 --loglevel=info
```

## Migration depuis l'ancienne architecture

Si vous aviez des scripts utilisant `celery -A app.tasks`, ils doivent être mis à jour:

**Avant:**
```bash
celery -A app.tasks worker --loglevel=info
```

**Après:**
```bash
celery -A app.celery_app worker --loglevel=info
```

**Dans le code Python:**

**Avant:**
```python
from app.tasks.pipeline import celery_app
```

**Après:**
```python
from app.celery_app import celery_app
# ou
from app.tasks import celery_app  # Compatibilité
```
