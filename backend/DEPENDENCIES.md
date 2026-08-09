# Dépendances RythmoAI Backend (§6.1, §18.4 CDC)

Ce document décrit la gestion des dépendances du backend RythmoAI, séparée par profils d'installation selon les besoins.

## Table des matières
- [Vue d'ensemble](#vue-densemble)
- [Profils d'installation](#profils-dinstallation)
- [Installation](#installation)
- [Vérification](#verification)
- [Compatibilité Python](#compatibilite-python)
- [Dépannage](#depannage)

## Vue d'ensemble

Les dépendances sont séparées en plusieurs fichiers pour permettre une installation modulaire:

```
backend/
├── requirements.txt            # Runtime de base (API, PostgreSQL, Celery)
├── requirements-ai-cpu.txt    # Moteurs IA CPU (Whisper, transformers, etc.)
├── requirements-ai-gpu.txt    # Moteurs IA GPU/CUDA (Demucs, WhisperX, etc.)
├── requirements-dev.txt       # Outils de développement et tests
├── pyproject.toml            # Configuration du projet (groupes optionnels)
└── requirements-lock.txt     # Versions verrouillées (reproductibilité)
```

## Profils d'installation

### 1. Runtime CPU (Minimum)
```bash
pip install -r requirements.txt
```
**Inclut:**
- FastAPI + Uvicorn (API web)
- SQLAlchemy async + asyncpg + aiosqlite (base de données)
- Pydantic + pydantic-settings (validation/config)
- Auth (JWT, argon2, pyotp)
- Stockage S3 (boto3)
- Export PDF (reportlab)
- Traitement audio/linguistique CPU (numpy, scipy, pyphen)
- Orchestration (Celery + Redis)

**Utilisation:** API de base sans fonctionnalités IA.

---

### 2. Runtime + IA CPU (Recommandé pour dev/staging)
```bash
pip install -r requirements.txt
pip install -r requirements-ai-cpu.txt
# ou: pip install .[cpu]
```
**Ajoute aux précédents:**
- PyTorch CPU (deep learning)
- Whisper (transcription)
- Transformers + wav2vec2 (émotions)
- Silero VAD (détection parole)
- Spacy FR (NLP)
- Librosa (analyse audio)
- Pyannote (diarisation, performaces CPU réduites)

**Utilisation:** Toutes fonctionnalités IA sur CPU.

---

### 3. Runtime + IA GPU (Production avec GPU)
```bash
pip install -r requirements.txt
pip install -r requirements-ai-cpu.txt
pip install -r requirements-ai-gpu.txt
# ou: pip install .[gpu]
```
**Ajoute:**
- PyTorch CUDA 11.8
- Demucs (séparation sources GPU)
- WhisperX (alignement GPU)
- Versions GPU optimisées des autres modules

**Prérequis:** GPU NVIDIA avec CUDA 11.8+, pilotes compatibles.

---

### 4. Développement complet
```bash
pip install -r requirements.txt
pip install -r requirements-ai-cpu.txt
pip install -r requirements-dev.txt
# ou: pip install .[all]
```
**Ajoute:**
- pytest + pytest-asyncio + pytest-cov (tests)
- httpx (test client asynchrone)
- ruff (linting)
- mypy (typage statique)
- pip-audit (sécurité)
- rich (logs colorés)
- pre-commit (git hooks)

---

## Installation

### Installation complète (CPU + Dev)
```bash
cd backend
pip install -r requirements.txt
pip install -r requirements-ai-cpu.txt
pip install -r requirements-dev.txt
```

### Installation GPU (production)
```bash
cd backend
pip install -r requirements.txt
pip install -r requirements-ai-gpu.txt
```

### Installation via pyproject.toml
```bash
# Runtime de base seulement
pip install .

# Avec IA CPU
pip install .[cpu]

# Avec IA GPU
pip install .[gpu]

# Tout (runtime + IA CPU + dev)
pip install .[all]
```

## Vérification

### Vérifier l'installation
```bash
# Tester les imports
python -c "import fastapi; import sqlalchemy; import asyncpg; print('OK')"

# Vérifier la configuration
python -c "from app.core.config import get_settings; s = get_settings(); print(s.DATABASE_URL)"
```

### Vérifier les dépendances
```bash
# Vérifier les conflits
pip check

# Audit de sécurité
pip-audit

# Liste des paquets installés
pip list
```

### Tests
```bash
# Tests unitaires (SQLite)
pytest tests/unit/ -v

# Tests d'intégration (PostgreSQL si disponible)
pytest tests/integration/test_postgresql_config.py -v
```

## Compatibilité Python

| Version Python | Supportée | Notes |
|---------------|-----------|-------|
| 3.13 | ✅ | Développement actif |
| 3.12 | ✅ | Testé |
| 3.11 | ✅ | Minimum recommandé |
| 3.10 | ✅ | Minimum supporté |
| < 3.10 | ❌ | Non supporté |

## Dépendances par fonctionnalité

### API & Web
| Package | Version | Description |
|---------|---------|-------------|
| fastapi | >=0.115.0 | Framework API asynchrone |
| uvicorn | >=0.34.0 | Serveur ASGI |

### Base de données
| Package | Version | Description |
|---------|---------|-------------|
| sqlalchemy | >=2.0.0 | ORM asynchrone |
| asyncpg | >=0.29.0 | Pilote PostgreSQL async |
| aiosqlite | >=0.19.0 | Pilote SQLite async (tests) |
| alembic | >=1.14.0 | Migrations |

### Auth & Sécurité
| Package | Version | Description |
|---------|---------|-------------|
| PyJWT | >=2.8.0 | Tokens JWT |
| argon2-cffi | >=23.1.0 | Hachage mots de passe |
| pyotp | >=2.10.0 | MFA/TOTP |

### Stockage
| Package | Version | Description |
|---------|---------|-------------|
| boto3 | >=1.34.0 | AWS S3 / MinIO |

### IA - Transcription
| Package | Version | Description |
|---------|---------|-------------|
| torch | >=2.2.0 | Framework deep learning |
| openai-whisper | >=20231117 | Transcription vocale |

### IA - Émotions & NLP
| Package | Version | Description |
|---------|---------|-------------|
| transformers | >=4.35.0 | Modèles pré-entraînés |
| librosa | >=0.10.0 | Analyse audio |
| spacy | >=3.7.0 | NLP (français) |

### IA - Audio
| Package | Version | Description |
|---------|---------|-------------|
| silero-vad | >=5.1.0 | Détection parole |
| pyannote.audio | >=3.0.0 | Diarisation |
| demucs | >=4.0.0 | Séparation sources (GPU) |
| whisperx | >=2.3.0 | Alignement (GPU) |

### Orchestration
| Package | Version | Description |
|---------|---------|-------------|
| celery | >=5.3.0 | Tâches asynchrones |
| redis | >=5.0.0 | Broker + cache |

## Variables d'environnement IA

| Variable | Valeurs | Défaut | Description |
|----------|---------|--------|-------------|
| SOURCE_SEPARATION_BACKEND | auto, spectral, demucs, off | auto | Backend séparation |
| FEATURE_LIP_SYNC | true/false | false | Sync labiale |
| FEATURE_CRDT | true/false | false | CRDT collaboratif |
| FEATURE_SOURCE_SEPARATION | true/false | false | Séparation sources |

## Dépannage

### Erreur: "No module named 'torch'"
```bash
# Pour CPU uniquement
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Pour GPU CUDA 11.8
pip install torch --index-url https://download.pytorch.org/whl/cu118
```

### Erreur: "CUDA out of memory"
```bash
# Limiter l'utilisation GPU
export CUDA_VISIBLE_DEVICES=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

### Configuration spacy
```bash
# Télécharger le modèle français
python -m spacy download fr_core_news_sm
```

### Problème avec asyncpg sur certains systèmes
```bash
# Installation manuelle des dépendances système
# Ubuntu/Debian:
sudo apt-get install libpq-dev python3-dev

# Redémarrer l'installation
pip install asyncpg
```

### Tests qui échouent avec "database is locked"
```bash
# Utiliser une base séparée pour les tests
export TEST_DATABASE_URL=sqlite+aiosqlite:///test.db
pytest
```
