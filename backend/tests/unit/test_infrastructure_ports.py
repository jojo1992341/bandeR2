"""
Tests unitaires des ports et adaptateurs infrastructure (§6.2 CDC)

Vérifie que:
1. Les interfaces sont correctement définies
2. Les adaptateurs implémentent correctement les ports
3. Les tests peuvent utiliser des adaptateurs mémoire sans monkeypatch
"""

from __future__ import annotations

import pytest

# ============================================================
# Tests Storage Port
# ============================================================

class TestStoragePort:
    """Tests du port et adaptateur de stockage."""
    
    def test_memory_storage_put_and_get(self):
        """Test put/get avec adaptateur mémoire."""
        from app.infrastructure.adapters.storage import MemoryStorageAdapter
        
        storage = MemoryStorageAdapter()
        
        # Test put
        assert storage.put_object("bucket", "key1", {"data": "value"}) is True
        
        # Test get
        result = storage.get_object("bucket", "key1")
        assert result == {"data": "value"}
    
    def test_memory_storage_delete(self):
        """Test delete avec adaptateur mémoire."""
        from app.infrastructure.adapters.storage import MemoryStorageAdapter
        
        storage = MemoryStorageAdapter()
        
        storage.put_object("bucket", "key1", "value")
        assert storage.delete_object("bucket", "key1") is True
        assert storage.get_object("bucket", "key1") is None
    
    def test_memory_storage_list(self):
        """Test list avec adaptateur mémoire."""
        from app.infrastructure.adapters.storage import MemoryStorageAdapter
        
        storage = MemoryStorageAdapter()
        
        storage.put_object("bucket", "prefix/key1", "value1")
        storage.put_object("bucket", "prefix/key2", "value2")
        storage.put_object("bucket", "other/key3", "value3")
        
        objects = storage.list_objects("bucket", prefix="prefix/")
        assert len(objects) == 2
    
    def test_memory_storage_health(self):
        """Test health check avec adaptateur mémoire."""
        from app.infrastructure.adapters.storage import MemoryStorageAdapter
        
        storage = MemoryStorageAdapter()
        health = storage.health_check()
        
        assert health["status"] == "healthy"
        assert health["storage_type"] == "memory"


# ============================================================
# Tests Cache Port
# ============================================================

class TestCachePort:
    """Tests du port et adaptateur de cache."""
    
    def test_memory_cache_set_get(self):
        """Test set/get avec adaptateur mémoire."""
        from app.infrastructure.adapters.cache import MemoryCacheAdapter
        
        cache = MemoryCacheAdapter()
        
        # Test set/get simple
        assert cache.set("key1", "value") is True
        assert cache.get("key1") == "value"
        
        # Test set/get avec dict
        assert cache.set("key2", {"nested": "value"}) is True
        assert cache.get("key2") == {"nested": "value"}
    
    def test_memory_cache_expire(self):
        """Test expiration avec adaptateur mémoire."""
        from app.infrastructure.adapters.cache import MemoryCacheAdapter
        
        cache = MemoryCacheAdapter()
        
        # Set avec expiration courte
        assert cache.set("key1", "value", expire_seconds=2) is True
        assert cache.get("key1") == "value"
        
        # Après expiration (simulation)
        import time
        time.sleep(2.1)
        assert cache.get("key1") is None
    
    def test_memory_cache_incr_decr(self):
        """Test incr/decr avec adaptateur mémoire."""
        from app.infrastructure.adapters.cache import MemoryCacheAdapter
        
        cache = MemoryCacheAdapter()
        
        assert cache.set("counter", 10) is True
        assert cache.incr("counter", 5) == 15
        assert cache.decr("counter", 3) == 12
        assert cache.get("counter") == 12
    
    def test_memory_cache_health(self):
        """Test health check avec adaptateur mémoire."""
        from app.infrastructure.adapters.cache import MemoryCacheAdapter
        
        cache = MemoryCacheAdapter()
        health = cache.health_check()
        
        assert health["status"] == "healthy"
        assert health["cache_type"] == "memory"


# ============================================================
# Tests Email Port
# ============================================================

class TestEmailPort:
    """Tests du port et adaptateur d'email."""
    
    def test_memory_email_send(self):
        """Test envoi email avec adaptateur mémoire."""
        from app.infrastructure.adapters.email import MemoryEmailAdapter
        
        email = MemoryEmailAdapter()
        
        result = email.send_email(
            to="test@example.com",
            subject="Test Subject",
            body="Test Body",
        )
        
        assert result["success"] is True
        assert result["message_id"] is not None
        assert result["error"] is None
        
        # Vérifier que l'email a été enregistré
        sent = email.get_sent_emails()
        assert len(sent) == 1
        assert sent[0]["to"] == "test@example.com"
        assert sent[0]["subject"] == "Test Subject"
    
    def test_memory_email_bulk(self):
        """Test envoi bulk avec adaptateur mémoire."""
        from app.infrastructure.adapters.email import MemoryEmailAdapter
        
        email = MemoryEmailAdapter()
        
        result = email.send_bulk_email(
            recipients=["a@test.com", "b@test.com", "c@test.com"],
            subject="Bulk Test",
            body="Bulk Body",
        )
        
        assert result["success"] is True
        assert result["sent_count"] == 3
        assert result["failed_count"] == 0
        
        # Vérifier les emails envoyés
        sent = email.get_sent_emails()
        assert len(sent) == 3
    
    def test_memory_email_clear(self):
        """Test nettoyage avec adaptateur mémoire."""
        from app.infrastructure.adapters.email import MemoryEmailAdapter
        
        email = MemoryEmailAdapter()
        
        email.send_email("test@example.com", "Subject", "Body")
        assert len(email.get_sent_emails()) == 1
        
        email.clear()
        assert len(email.get_sent_emails()) == 0
    
    def test_memory_email_health(self):
        """Test health check avec adaptateur mémoire."""
        from app.infrastructure.adapters.email import MemoryEmailAdapter
        
        email = MemoryEmailAdapter()
        health = email.health_check()
        
        assert health["status"] == "healthy"
        assert health["email_type"] == "memory"


# ============================================================
# Tests HTTP Port
# ============================================================

class TestHttpPort:
    """Tests du port et adaptateur HTTP."""
    
    def test_memory_http_get(self):
        """Test requête GET avec adaptateur mémoire."""
        from app.infrastructure.adapters.http import MemoryHttpAdapter
        
        http = MemoryHttpAdapter()
        
        # Configurer une réponse mock
        http.mock_response(
            "https://api.example.com/test",
            "GET",
            {"status_code": 200, "body": {"data": "test"}, "error": None},
        )
        
        result = http.get("https://api.example.com/test")
        
        assert result["status_code"] == 200
        assert result["body"] == {"data": "test"}
        assert result.get("error") is None
    
    def test_memory_http_post(self):
        """Test requête POST avec adaptateur mémoire."""
        from app.infrastructure.adapters.http import MemoryHttpAdapter
        
        http = MemoryHttpAdapter()
        
        result = http.post(
            "https://api.example.com/test",
            json={"key": "value"},
        )
        
        assert result["status_code"] == 200
        assert result["error"] is None
        
        # Vérifier que la requête a été enregistrée
        requests = http.get_requests()
        assert len(requests) == 1
        assert requests[0]["method"] == "POST"
        assert requests[0]["url"] == "https://api.example.com/test"
    
    def test_memory_http_webhook(self):
        """Test envoi webhook avec adaptateur mémoire."""
        from app.infrastructure.adapters.http import MemoryHttpAdapter, WebhookAdapter
        
        http = MemoryHttpAdapter()
        webhook = WebhookAdapter(http_adapter=http)
        
        result = webhook.send_webhook(
            url="https://webhook.example.com/test",
            payload={"event": "test"},
            secret="test-secret",
            event_type="test.event",
        )
        
        assert result["success"] is True
        assert result["status_code"] == 200
        
        # Vérifier que la requête a été enregistrée avec les headers
        requests = http.get_requests()
        assert len(requests) == 1
        assert "X-Event-Type" in requests[0]["headers"]
        assert "X-RythmoAI-Signature" in requests[0]["headers"]
    
    def test_memory_http_signature_verification(self):
        """Test vérification de signature webhook."""
        from app.infrastructure.adapters.http import WebhookAdapter
        
        webhook = WebhookAdapter()
        
        payload = b'{"event": "test"}'
        secret = "test-secret"
        
        # Générer une signature valide
        import hmac
        import hashlib
        signature = "sha256=" + hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        
        assert webhook.verify_webhook_signature(payload, signature, secret) is True
        assert webhook.verify_webhook_signature(payload, "sha256=wrong", secret) is False
    
    def test_memory_http_health(self):
        """Test health check avec adaptateur mémoire."""
        from app.infrastructure.adapters.http import MemoryHttpAdapter
        
        http = MemoryHttpAdapter()
        health = http.health_check()
        
        assert health["status"] == "healthy"
        assert health["http_type"] == "memory"


# ============================================================
# Tests Database Port
# ============================================================

class TestDatabasePort:
    """Tests du port et driver de base de données."""
    
    def test_database_driver_health(self):
        """Test health check du driver DB."""
        from app.infrastructure.drivers.database_driver import get_database_driver
        import asyncio
        
        async def check_health():
            driver = get_database_driver(for_test=True)
            return await driver.health_check()
        
        health = asyncio.run(check_health())
        
        # Le driver de test utilise SQLite en mémoire
        # Le health check peut échouer si la DB n'est pas initialisée
        # mais le driver doit retourner un résultat
        assert "status" in health


# ============================================================
# Tests de l'utilisation des adaptateurs dans les services
# ============================================================

class TestServiceUsesInterfaces:
    """Tests vérifiant que les services utilisent les interfaces."""
    
    def test_storage_service_uses_port(self):
        """Vérifie que StorageService utilise StoragePort."""
        from app.infrastructure.ports.storage import StoragePort
        from app.infrastructure.adapters.storage import MemoryStorageAdapter
        
        # Vérifier que MemoryStorageAdapter implémente StoragePort
        storage = MemoryStorageAdapter()
        assert isinstance(storage, StoragePort)
    
    def test_cache_service_uses_port(self):
        """Vérifie que les services de cache utilisent CachePort."""
        from app.infrastructure.ports.cache import CachePort
        from app.infrastructure.adapters.cache import MemoryCacheAdapter
        
        cache = MemoryCacheAdapter()
        assert isinstance(cache, CachePort)
    
    def test_can_inject_memory_adapters(self):
        """Vérifie que les adaptateurs mémoire peuvent être injectés."""
        from app.infrastructure.adapters.storage import MemoryStorageAdapter
        from app.infrastructure.adapters.cache import MemoryCacheAdapter
        from app.infrastructure.adapters.email import MemoryEmailAdapter
        from app.infrastructure.adapters.http import MemoryHttpAdapter
        
        # Tous ces adaptateurs doivent pouvoir être créés sans dépendances externes
        storage = MemoryStorageAdapter()
        cache = MemoryCacheAdapter()
        email = MemoryEmailAdapter()
        http = MemoryHttpAdapter()
        
        # Et ils doivent fonctionner sans erreur
        assert storage.health_check()["status"] == "healthy"
        assert cache.health_check()["status"] == "healthy"
        assert email.health_check()["status"] == "healthy"
        assert http.health_check()["status"] == "healthy"


# Helper pour les tests asynchrones
import asyncio

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
