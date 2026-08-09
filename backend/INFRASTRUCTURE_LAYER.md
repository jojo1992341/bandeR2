# Couche Infrastructure - Ports & Adaptateurs (§6.2 CDC)

Ce document décrit la couche infrastructure mise en place selon les principes de Clean Architecture.

## Table des matières
- [Principe](#principe)
- [Architecture](#architecture)
- [Ports (Interfaces)](#ports-interfaces)
- [Adaptateurs](#adaptateurs)
- [Drivers (Fabriques)](#drivers-fabriques)
- [Utilisation](#utilisation)
- [Tests](#tests)
- [Migration](#migration)

## Principe (§6.2 CDC)

La couche infrastructure suit les principes de Clean Architecture:
1. **Ports (interfaces)**: Définissent les contrats stables
2. **Adaptateurs (implémentations)**: Implémentent les ports pour des technologies spécifiques
3. **Drivers (fabriques)**: Fournissent les adaptateurs configurés

Bénéfices:
- **Tests isolés**: Les adaptateurs mémoire permettent les tests sans dépendances externes
- **Injection de dépendances**: Les services métier dépendent d'interfaces, pas d'implémentations
- **Évolutivité**: Changer de technologie sans modifier les services métier

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Services Métier (Business Logic)              │
│  Ex: FeedbackService, EmotionService, PublicApiService         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Dépendent des interfaces (ports)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Ports (Interfaces Stables)                   │
│  - StoragePort          - CachePort                            │
│  - EmailPort            - HttpClientPort                       │
│  - WebhookSenderPort    - DatabasePort                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Implémentent les interfaces
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Adaptateurs (Implémentations)                │
│  ┌─────────────────┬──────────────────────────────────────────┐│
│  │ Production      │ Tests                                     ││
│  ├─────────────────┼──────────────────────────────────────────┤│
│  │ S3StorageAdapter│ MemoryStorageAdapter                     ││
│  │ RedisCacheAdapter│ MemoryCacheAdapter                       ││
│  │ SmtpEmailAdapter │ MemoryEmailAdapter                       ││
│  │ HttpAdapter     │ MemoryHttpAdapter                        ││
│  │ DatabaseDriver  │ DatabaseDriver(for_test=True)            ││
│  └─────────────────┴──────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Utilisent les bibliothèques externes
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Bibliothèques Externes                        │
│  - boto3 (S3)        - redis-py (Redis)                        │
│  - httpx (HTTP)      - SQLAlchemy async (DB)                   │
│  - smtplib (Email)   - etc.                                    │
└─────────────────────────────────────────────────────────────────┘
```

## Ports (Interfaces)

### StoragePort (`app/infrastructure/ports/storage.py`)

Interface pour le stockage d'objets (S3, MinIO).

```python
class StoragePort(ABC):
    @abstractmethod
    def put_object(bucket, key, data, content_type) -> bool: ...
    @abstractmethod
    def get_object(bucket, key) -> Optional[Any]: ...
    @abstractmethod
    def delete_object(bucket, key) -> bool: ...
    @abstractmethod
    def list_objects(bucket, prefix, max_keys) -> list[dict]: ...
    @abstractmethod
    def generate_presigned_url(bucket, key, ...) -> Optional[str]: ...
    @abstractmethod
    def upload_file(local_path, bucket, key) -> bool: ...
    @abstractmethod
    def download_file(bucket, key, local_path) -> bool: ...
    @abstractmethod
    def health_check() -> dict: ...
```

### CachePort (`app/infrastructure/ports/cache.py`)

Interface pour le cache distribué (Redis).

```python
class CachePort(ABC):
    @abstractmethod
    def get(key) -> Optional[Any]: ...
    @abstractmethod
    def set(key, value, expire_seconds) -> bool: ...
    @abstractmethod
    def delete(key) -> bool: ...
    @abstractmethod
    def exists(key) -> bool: ...
    @abstractmethod
    def incr(key, amount) -> Optional[int]: ...
    @abstractmethod
    def decr(key, amount) -> Optional[int]: ...
    @abstractmethod
    def expire(key, seconds) -> bool: ...
    @abstractmethod
    def ttl(key) -> Optional[int]: ...
    @abstractmethod
    def delete_pattern(pattern) -> int: ...
    @abstractmethod
    def health_check() -> dict: ...
```

### EmailPort (`app/infrastructure/ports/email.py`)

Interface pour l'envoi d'emails.

```python
class EmailPort(ABC):
    @abstractmethod
    def send_email(to, subject, body, html_body, ...) -> dict: ...
    @abstractmethod
    def send_template(to, template_name, context, ...) -> dict: ...
    @abstractmethod
    def send_bulk_email(recipients, subject, body, ...) -> dict: ...
    @abstractmethod
    def health_check() -> dict: ...
```

### HttpClientPort & WebhookSenderPort (`app/infrastructure/ports/http.py`)

Interfaces pour les requêtes HTTP et webhooks.

```python
class HttpClientPort(ABC):
    @abstractmethod
    def get(url, headers, params, timeout) -> dict: ...
    @abstractmethod
    def post(url, headers, data, json, timeout) -> dict: ...
    @abstractmethod
    def put(url, headers, data, json, timeout) -> dict: ...
    @abstractmethod
    def delete(url, headers, timeout) -> dict: ...
    @abstractmethod
    def patch(url, headers, data, json, timeout) -> dict: ...
    @abstractmethod
    def health_check() -> dict: ...

class WebhookSenderPort(ABC):
    @abstractmethod
    def send_webhook(url, payload, secret, event_type, idempotency_key) -> dict: ...
    @abstractmethod
    def verify_webhook_signature(payload, signature, secret, algorithm) -> bool: ...
```

### DatabasePort (`app/infrastructure/ports/database.py`)

Interface pour l'accès à la base de données.

```python
class DatabasePort(ABC):
    @abstractmethod
    async def get_session() -> AsyncGenerator[AsyncSession, None]: ...
    @abstractmethod
    async def execute(statement) -> Any: ...
    @abstractmethod
    async def get_one(statement) -> Optional[Any]: ...
    @abstractmethod
    async def get_all(statement) -> list[Any]: ...
    @abstractmethod
    async def add(entity) -> Any: ...
    @abstractmethod
    async def add_all(entities) -> list[Any]: ...
    @abstractmethod
    async def commit() -> None: ...
    @abstractmethod
    async def rollback() -> None: ...
    @abstractmethod
    async def refresh(entity) -> None: ...
    @abstractmethod
    async def delete(entity) -> None: ...
    @abstractmethod
    async def health_check() -> dict: ...
```

## Adaptateurs

### S3StorageAdapter (`app/infrastructure/adapters/storage.py`)

Implémentation S3 utilisant boto3.

```python
from app.infrastructure.adapters.storage import S3StorageAdapter

storage = S3StorageAdapter()
storage.put_object("bucket", "key", {"data": "value"})
result = storage.get_object("bucket", "key")
```

### MemoryStorageAdapter

Implémentation en mémoire pour les tests.

```python
from app.infrastructure.adapters.storage import MemoryStorageAdapter

storage = MemoryStorageAdapter()  # Pas de dépendances externes
storage.put_object("bucket", "key", "value")
assert storage.get_object("bucket", "key") == "value"
```

### RedisCacheAdapter (`app/infrastructure/adapters/cache.py`)

Implémentation Redis utilisant redis-py.

```python
from app.infrastructure.adapters.cache import RedisCacheAdapter

cache = RedisCacheAdapter()
cache.set("key", "value", expire_seconds=3600)
value = cache.get("key")
```

### MemoryCacheAdapter

Implémentation en mémoire pour les tests.

```python
from app.infrastructure.adapters.cache import MemoryCacheAdapter

cache = MemoryCacheAdapter()
cache.set("counter", 10)
cache.incr("counter", 5)  # 15
```

### SmtpEmailAdapter (`app/infrastructure/adapters/email.py`)

Implémentation SMTP pour l'envoi d'emails.

```python
from app.infrastructure.adapters.email import SmtpEmailAdapter

email = SmtpEmailAdapter()
result = email.send_email(
    to="user@example.com",
    subject="Welcome",
    body="Hello!",
)
```

### MemoryEmailAdapter

Adaptateur mémoire pour les tests (enregistre les emails dans une liste).

```python
from app.infrastructure.adapters.email import MemoryEmailAdapter

email = MemoryEmailAdapter()
email.send_email("test@example.com", "Subject", "Body")

# Vérifier les emails envoyés
sent = email.get_sent_emails()
assert len(sent) == 1
assert sent[0]["to"] == "test@example.com"
```

### HttpAdapter & WebhookAdapter (`app/infrastructure/adapters/http.py`)

Implémentations HTTP utilisant httpx.

```python
from app.infrastructure.adapters.http import HttpAdapter, WebhookAdapter

http = HttpAdapter()
response = http.get("https://api.example.com/data")

webhook = WebhookAdapter(http_adapter=http)
result = webhook.send_webhook(
    url="https://webhook.example.com",
    payload={"event": "test"},
    secret="webhook-secret",
)
```

### MemoryHttpAdapter

Adaptateur mémoire pour les tests.

```python
from app.infrastructure.adapters.http import MemoryHttpAdapter, WebhookAdapter

http = MemoryHttpAdapter()
http.mock_response("https://api.example.com", "GET", {
    "status_code": 200,
    "body": {"data": "mocked"},
})

response = http.get("https://api.example.com")
assert response["body"] == {"data": "mocked"}
```

### DatabaseDriver (`app/infrastructure/drivers/database_driver.py`)

Driver de base de données utilisant SQLAlchemy async.

```python
from app.infrastructure.drivers.database_driver import get_database_driver

driver = get_database_driver(for_test=False)
await driver.health_check()
```

## Drivers (Fabriques)

Les drivers fournissent des méthodes pour obtenir les adaptateurs configurés.

### Storage Driver (`app/infrastructure/drivers/storage_driver.py`)

```python
from app.infrastructure.drivers.storage_driver import (
    get_storage_adapter,
    get_s3_storage,
    get_memory_storage,
)

# Production
storage = get_s3_storage()

# Test
storage = get_storage_adapter(for_test=True)
```

### Cache Driver (`app/infrastructure/drivers/cache_driver.py`)

```python
from app.infrastructure.drivers.cache_driver import (
    get_cache_adapter,
    get_redis_cache,
    get_memory_cache,
)

# Production
cache = get_redis_cache()

# Test
cache = get_cache_adapter(for_test=True)
```

### Email Driver (`app/infrastructure/drivers/email_driver.py`)

```python
from app.infrastructure.drivers.email_driver import (
    get_email_adapter,
    get_smtp_email,
    get_memory_email,
)

# Production
email = get_smtp_email()

# Test
email = get_email_adapter(for_test=True)
```

### HTTP Driver (`app/infrastructure/drivers/http_driver.py`)

```python
from app.infrastructure.drivers.http_driver import (
    get_http_adapter,
    get_webhook_adapter,
    get_memory_http,
    get_memory_webhook,
)

# Production
http = get_http_adapter()
webhook = get_webhook_adapter(http_adapter=http)

# Test
http = get_memory_http()
webhook = get_memory_webhook()
```

### Database Driver (`app/infrastructure/drivers/database_driver.py`)

```python
from app.infrastructure.drivers.database_driver import (
    get_database_driver,
    get_production_database,
    get_test_database,
)

# Production
db = get_production_database()

# Test
db = get_test_database()
```

## Utilisation

### Injection dans les services métier

Les services métier doivent dépendre des interfaces (ports), pas des implémentations.

```python
from app.infrastructure.ports.storage import StoragePort
from app.infrastructure.ports.cache import CachePort

class MonService:
    def __init__(self, storage: StoragePort, cache: CachePort):
        self.storage = storage
        self.cache = cache
    
    def process(self, key: str):
        # Utiliser les interfaces
        cached = self.cache.get(key)
        if cached:
            return cached
        
        data = self.storage.get_object("bucket", key)
        self.cache.set(key, data, expire_seconds=3600)
        return data
```

### Tests unitaires

```python
from app.infrastructure.adapters.storage import MemoryStorageAdapter
from app.infrastructure.adapters.cache import MemoryCacheAdapter
from mon_module import MonService

def test_mon_service():
    storage = MemoryStorageAdapter()
    cache = MemoryCacheAdapter()
    
    service = MonService(storage=storage, cache=cache)
    
    # Tester sans dépendances externes
    result = service.process("test-key")
    assert result is not None
```

## Tests

### Lancer les tests

```bash
cd backend
python -m pytest tests/unit/test_infrastructure_ports.py -v
```

### Résultat attendu

```
============================= test session starts ==============================
...
tests/unit/test_infrastructure_ports.py::TestStoragePort::test_memory_storage_put_and_get PASSED
tests/unit/test_infrastructure_ports.py::TestStoragePort::test_memory_storage_delete PASSED
tests/unit/test_infrastructure_ports.py::TestStoragePort::test_memory_storage_list PASSED
tests/unit/test_infrastructure_ports.py::TestStoragePort::test_memory_storage_health PASSED
tests/unit/test_infrastructure_ports.py::TestCachePort::test_memory_cache_set_get PASSED
tests/unit/test_infrastructure_ports.py::TestCachePort::test_memory_cache_expire PASSED
tests/unit/test_infrastructure_ports.py::TestCachePort::test_memory_cache_incr_decr PASSED
tests/unit/test_infrastructure_ports.py::TestCachePort::test_memory_cache_health PASSED
tests/unit/test_infrastructure_ports.py::TestEmailPort::test_memory_email_send PASSED
tests/unit/test_infrastructure_ports.py::TestEmailPort::test_memory_email_bulk PASSED
tests/unit/test_infrastructure_ports.py::TestEmailPort::test_memory_email_clear PASSED
tests/unit/test_infrastructure_ports.py::TestEmailPort::test_memory_email_health PASSED
tests/unit/test_infrastructure_ports.py::TestHttpPort::test_memory_http_get PASSED
tests/unit/test_infrastructure_ports.py::TestHttpPort::test_memory_http_post PASSED
tests/unit/test_infrastructure_ports.py::TestHttpPort::test_memory_http_webhook PASSED
tests/unit/test_infrastructure_ports.py::TestHttpPort::test_memory_http_signature_verification PASSED
tests/unit/test_infrastructure_ports.py::TestHttpPort::test_memory_http_health PASSED
tests/unit/test_infrastructure_ports.py::TestDatabasePort::test_database_driver_health PASSED
tests/unit/test_infrastructure_ports.py::TestServiceUsesInterfaces::test_storage_service_uses_port PASSED
tests/unit/test_infrastructure_ports.py::TestServiceUsesInterfaces::test_cache_service_uses_port PASSED
tests/unit/test_infrastructure_ports.py::TestServiceUsesInterfaces::test_can_inject_memory_adapters PASSED
======================== 21 passed, 1 warning in 2.65s =========================
```

## Migration

### Étape 1: Identifier les dépendances directes

```bash
grep -r "boto3\|redis\|smtplib\|requests\|httpx" app/services/ --include="*.py"
```

### Étape 2: Créer les interfaces si nécessaire

Si un service utilise directement boto3, créez un port et un adaptateur.

### Étape 3: Mettre à jour les services

Remplacez les imports directs par des injections d'interfaces.

```python
# AVANT
from app.core.storage import get_s3_client

def mon_service():
    s3 = get_s3_client()
    s3.get_object(...)

# APRÈS
from app.infrastructure.ports.storage import StoragePort

class MonService:
    def __init__(self, storage: StoragePort):
        self.storage = storage
    
    def process(self):
        self.storage.get_object(...)
```

### Étape 4: Utiliser les adaptateurs mémoire pour les tests

```python
# test_mon_service.py
from app.infrastructure.adapters.storage import MemoryStorageAdapter
from mon_module import MonService

def test_mon_service():
    storage = MemoryStorageAdapter()
    service = MonService(storage=storage)
    # ...
```

## Fichiers créés

```
backend/app/infrastructure/
├── __init__.py
├── ports/
│   ├── __init__.py
│   ├── storage.py         # StoragePort
│   ├── cache.py           # CachePort
│   ├── email.py           # EmailPort
│   ├── http.py            # HttpClientPort, WebhookSenderPort
│   └── database.py        # DatabasePort
├── adapters/
│   ├── __init__.py
│   ├── storage.py         # S3StorageAdapter, MemoryStorageAdapter
│   ├── cache.py           # RedisCacheAdapter, MemoryCacheAdapter
│   ├── email.py           # SmtpEmailAdapter, MemoryEmailAdapter
│   └── http.py            # HttpAdapter, WebhookAdapter, MemoryHttpAdapter
└── drivers/
    ├── __init__.py
    ├── storage_driver.py  # get_storage_adapter, get_s3_storage, get_memory_storage
    ├── cache_driver.py    # get_cache_adapter, get_redis_cache, get_memory_cache
    ├── email_driver.py    # get_email_adapter, get_smtp_email, get_memory_email
    ├── http_driver.py     # get_http_adapter, get_webhook_adapter, etc.
    └── database_driver.py # get_database_driver, get_production_database, get_test_database
```

## Documentation

- `INFRASTRUCTURE_LAYER.md` - Ce document
- `SEPARATION_CALCUL_STOCKAGE.md` - Séparation calcul/storage (§5.4)
- `DB_CONFIGURATION.md` - Configuration DB asynchrone
- `DEPENDENCIES.md` - Dépendances du projet
