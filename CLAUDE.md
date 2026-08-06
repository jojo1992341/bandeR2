# CLAUDE.md — RythmoAI / bandeR2 (Claude Code Rules)

## Stack imposée (ne jamais dévier)
- **Frontend** : HTML5 / CSS3 / JavaScript natif (ES2022+). **Aucun framework lourd** (pas de React, Vue, Angular, Svelte, etc.). Utiliser Web Components, WaveSurfer.js, Video.js, Canvas 2D.
- **Backend** : Python 3.13+ / FastAPI (async). Clean Architecture stricte (§6.2 du CDC).
- **Base de données** : PostgreSQL + SQLAlchemy 2.0 async + Alembic.
- **Tâches asynchrones** : Celery + Redis.
- **Stockage** : MinIO (S3-compatible).
- **Tests** : pytest (unit + integration + e2e), ruff, black, Playwright (frontend), k6 (perf).
- **Lint/Format** : ruff + black (backend), eslint + prettier si besoin (frontend natif).

## Arborescence backend (Clean Architecture) — à respecter strictement
```
backend/
├── app/
│   ├── main.py
│   ├── api/                 # Routers FastAPI (v1/)
│   ├── core/                # Config, security, dependencies
│   ├── domain/              # Entités métier pures
│   ├── services/            # Logique métier
│   ├── repositories/        # Accès données (SQLAlchemy)
│   ├── tasks/               # Tâches Celery
│   ├── ai/                  # Intégrations IA (Whisper, etc.)
│   ├── infrastructure/      # DB, cache, storage, external
│   ├── models/              # SQLAlchemy models
│   ├── schemas/             # Pydantic models
│   ├── alembic/             # Migrations
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── e2e/
```

## Règles strictes pour tous les goals
- **MoSCoW** : Ne jamais implémenter un `Could have` avant que les `Must have` de l'epic soient verts.
- Chaque goal doit être **vérifiable** avec les skills de vérification (.claude/skills/).
- Toujours utiliser `git worktree` pour paralléliser des goals indépendants.
- Avant chaque phase majeure : `/code-review`.
- Pas de `print()` en production ; utiliser logging structuré.
- Toutes les réponses API doivent être validées par Pydantic.
- Multi-tenant strict via `studio_id` + Row Level Security (RLS) PostgreSQL.
- Jamais de données sensibles en clair (Argon2id, AES-256, signed URLs ≤ 10 min).

## Commandes de référence
```bash
# Backend
uvicorn app.main:app --reload
pytest -q --cov=app
ruff check . && black --check .
alembic upgrade head

# Frontend (natif)
python -m http.server 8080   # ou serve via nginx
npx playwright test

# Docker
docker compose up -d --build
docker compose ps
```

## Objectif du projet
RythmoAI / bandeR2 : Outil professionnel de génération et d'édition de **bandes rythmo** (rythmo bands) pour le doublage audiovisuel.
Cible : WER < 8 %, écart synchro < 80 ms, pipeline 20 min < 10 min (GPU).

Document généré le 2026-08-06. Suivre le plan Goals.md séquentiellement.
