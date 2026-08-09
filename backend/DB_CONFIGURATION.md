# Configuration de Base de Données Asynchrone (§9.1, §18.4 CDC)

Ce document décrit la configuration SQLAlchemy 2.0 asynchrone avec asyncpg pour PostgreSQL 16.

## Table des matières
- [Vue d'ensemble](#vue-densemble)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Tests](#tests)
- [Migration](#migration)

## Vue d'ensemble

L'application backend utilise maintenant:
- **SQLAlchemy 2.0 asynchrone** avec `AsyncEngine` et `AsyncSession`
- **asyncpg** comme pilote PostgreSQL asynchrone
- **aiosqlite** pour les tests unitaires (SQLite asynchrone)
- **pydantic-settings** pour le chargement validé du fichier `.env`

## Architecture

```
app/
├── core/
│   ├── config.py          # Configuration pydantic-settings
│   └── database.py        # Moteur et sessions asynchrones
├── models/
│   └── base.py            # Base déclarative SQLAlchemy
└── api/v1/
    └── projects.py        # Exemple: routes utilisant get_db()
```

### Composants principaux

| Composant | Description |
|-----------|-------------|
| `Settings` | Configuration validée avec chargement `.env` |
| `AsyncEngine` | Moteur SQLAlchemy asynchrone |
| `AsyncSession` | Session ORM asynchrone |
| `get_db()` | Dépendance FastAPI pour les routes |
| `SessionLocal` | Alias synchrone (compatibilité legacy) |

## Configuration

### Fichier .env

Copiez `.env.example` en `.env` et adaptez les valeurs:

```bash
# Base de données (Option 1: URL complète)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rythmoai

# Ou Option 2: Composants individuels
DB_ENGINE=postgresql+asyncpg
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432
DB_NAME=rythmoai

# Tests (SQLite asynchrone)
TEST_DATABASE_URL=sqlite+aiosqlite:///:memory:
```

### Dépendances

```bash
pip install -r requirements.txt
```

Les dépendances clés sont:
- `sqlalchemy[asyncio]>=2.0.0`
- `asyncpg>=0.29.0` (PostgreSQL asynchrone)
- `aiosqlite>=0.19.0` (SQLite asynchrone pour tests)
- `pydantic-settings>=2.0.0` (chargement .env)

## Utilisation

### Dans les routes FastAPI

```python
from fastapi import APIRouter, Depends
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

@router.get("/items")
async def get_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Item))
    items = result.scalars().all()
    return items
```

### Dans les tâches Celery (compatibilité legacy)

```python
from app.core.database import SessionLocal

def my_task():
    db = SessionLocal()
    try:
        # Opérations synchrones
        items = db.query(Item).all()
    finally:
        db.close()
```

### Dans les scripts

```python
import asyncio
from app.core.database import database_session
from sqlalchemy import select
from app.models import Item

async def main():
    async with database_session() as session:
        result = await session.execute(select(Item))
        items = result.scalars().all()

asyncio.run(main())
```

## Tests

### Tests unitaires (SQLite asynchrone)

```bash
pytest tests/ -m unit -v
```

Les tests unitaires utilisent SQLite en mémoire avec aiosqlite.

### Tests d'intégration (PostgreSQL)

```bash
# Configurer DATABASE_URL pour pointer vers un PostgreSQL de test
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rythmoai_test
pytest tests/integration/test_postgresql_config.py -v
```

### Fichier conftest.py

Le fichier `tests/conftest.py` fournit des fixtures:
- `async_test_db`: Session SQLite asynchrone par test
- `client`: Client de test FastAPI
- `async_pg_session`: Session PostgreSQL (si disponible)

## Migration

### Alembic

Les migrations sont exécutées avec:

```bash
# Upgrade to latest
alembic upgrade head

# Check current version
alembic current

# Générer une nouvelle migration
alembic revision --autogenerate -m "description"
```

### Migration du code existant

#### Routes synchrone → asynchrone

**Avant:**
```python
from sqlalchemy.orm import Session
from app.core.database import get_db

@router.get("/items")
def get_items(db: Session = Depends(get_db)):
    items = db.query(Item).all()
    return items
```

**Après:**
```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db

@router.get("/items")
async def get_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Item))
    items = result.scalars().all()
    return items
```

#### Requêtes

| Synchrone | Asynchrone |
|-----------|------------|
| `db.query(Model).all()` | `result = await db.execute(select(Model)); result.scalars().all()` |
| `db.query(Model).filter_by(x=1).first()` | `result = await db.execute(select(Model).where(Model.x == 1)); result.scalar_one_or_none()` |
| `db.add(obj)` | `db.add(obj)` (identique) |
| `db.commit()` | `await db.commit()` |
| `db.refresh(obj)` | `await db.refresh(obj)` |

## Compatibilité

### SessionLocal (deprecated)

Pour maintenir la compatibilité avec le code existant (tâches Celery, etc.), `SessionLocal` est toujours disponible mais créé une session synchrone.

**Attention:** L'utilisation de `SessionLocal` nécessite `psycopg2` ou un autre pilote sync PostgreSQL installé.

### get_db_sync() (deprecated)

La fonction `get_db_sync()` est maintenue pour la compatibilité mais est dépréciée. Nouveaux codes doivent utiliser `get_db()`.

## Dépannage

### Erreur "No module named 'psycopg2'"

Si vous utilisez `SessionLocal`, installez psycopg2:
```bash
pip install psycopg2-binary
```

Ou utilisez exclusivement l'API asynchrone avec asyncpg.

### Erreur de pool de connexions

Pour PostgreSQL, le pool est configuré avec:
- `pool_size=10`
- `max_overflow=20`
- `pool_recycle=3600`

Ajustez ces valeurs dans `app/core/database.py` selon vos besoins.

### Tests échouent avec "database is locked"

Utilisez une base SQLite séparée pour chaque test ou utilisez le mode WAL:
```python
engine = create_async_engine("sqlite+aiosqlite:///test.db", echo=False)
```
