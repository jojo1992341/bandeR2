"""
Adaptateur de Cache Redis (§10.1, §6.2 CDC)

Implémente CachePort en utilisant redis-py.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import redis

from app.core.config import get_settings
from app.infrastructure.ports.cache import CachePort


class RedisCacheAdapter(CachePort):
    """
    Adaptateur Redis utilisant redis-py (sync).
    
    Implémente CachePort pour Redis.
    """
    
    def __init__(self, settings=None, redis_client=None):
        """
        Initialise l'adaptateur Redis.
        
        Args:
            settings: Configuration (défaut: get_settings()).
            redis_client: Client Redis pré-construit (pour les tests).
        """
        self._settings = settings or get_settings()
        self._client = redis_client
        self._prefix = "rythmoai:"
    
    @property
    def client(self) -> redis.Redis:
        """Retourne le client Redis (lazy initialization)."""
        if self._client is None:
            url = self._settings.REDIS_URL or "redis://localhost:6379/0"
            self._client = redis.from_url(url, decode_responses=True)
        return self._client
    
    def _make_key(self, key: str) -> str:
        """Prépare la clé avec préfixe."""
        return f"{self._prefix}{key}"
    
    def get(self, key: str) -> Optional[Any]:
        """Récupère une valeur du cache."""
        full_key = self._make_key(key)
        
        try:
            value = self.client.get(full_key)
            if value is None:
                return None
            
            # Tenter de décoder comme JSON
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except Exception:
            return None
    
    def set(
        self,
        key: str,
        value: Any,
        expire_seconds: Optional[int] = None
    ) -> bool:
        """Stocke une valeur dans le cache."""
        full_key = self._make_key(key)
        
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            elif not isinstance(value, str):
                value = str(value)
            
            if expire_seconds:
                self.client.setex(full_key, expire_seconds, value)
            else:
                self.client.set(full_key, value)
            
            return True
        except Exception:
            return False
    
    def delete(self, key: str) -> bool:
        """Supprime une clé du cache."""
        full_key = self._make_key(key)
        
        try:
            return bool(self.client.delete(full_key))
        except Exception:
            return False
    
    def exists(self, key: str) -> bool:
        """Vérifie si une clé existe."""
        full_key = self._make_key(key)
        
        try:
            return bool(self.client.exists(full_key))
        except Exception:
            return False
    
    def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """Incrémente une valeur."""
        full_key = self._make_key(key)
        
        try:
            return self.client.incr(full_key, amount)
        except Exception:
            return None
    
    def decr(self, key: str, amount: int = 1) -> Optional[int]:
        """Décrémente une valeur."""
        full_key = self._make_key(key)
        
        try:
            return self.client.decr(full_key, amount)
        except Exception:
            return None
    
    def expire(self, key: str, seconds: int) -> bool:
        """Définit un TTL."""
        full_key = self._make_key(key)
        
        try:
            return bool(self.client.expire(full_key, seconds))
        except Exception:
            return False
    
    def ttl(self, key: str) -> Optional[int]:
        """Récupère le TTL."""
        full_key = self._make_key(key)
        
        try:
            return self.client.ttl(full_key)
        except Exception:
            return None
    
    def delete_pattern(self, pattern: str) -> int:
        """Supprime les clés correspondant à un pattern."""
        full_pattern = self._make_key(pattern)
        
        try:
            keys = self.client.keys(full_pattern)
            if keys:
                return self.client.delete(*keys)
            return 0
        except Exception:
            return 0
    
    def health_check(self) -> dict:
        """Vérifie la santé de Redis."""
        try:
            self.client.ping()
            return {
                "status": "healthy",
                "cache_type": "redis",
                "url": self._settings.REDIS_URL,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }


class MemoryCacheAdapter(CachePort):
    """
    Adaptateur de cache en mémoire (pour les tests).
    
    Implémente CachePort en utilisant un dictionnaire.
    """
    
    def __init__(self):
        """Initialise le cache mémoire."""
        self._cache: dict[str, tuple[Any, Optional[float]]] = {}
    
    def get(self, key: str) -> Optional[Any]:
        """Récupère une valeur du cache."""
        if key not in self._cache:
            return None
        
        value, expiry = self._cache[key]
        
        # Vérifier expiration
        if expiry is not None:
            import time
            if time.time() > expiry:
                del self._cache[key]
                return None
        
        return value
    
    def set(
        self,
        key: str,
        value: Any,
        expire_seconds: Optional[int] = None
    ) -> bool:
        """Stocke une valeur dans le cache."""
        import time
        
        expiry = None
        if expire_seconds:
            expiry = time.time() + expire_seconds
        
        self._cache[key] = (value, expiry)
        return True
    
    def delete(self, key: str) -> bool:
        """Supprime une clé du cache."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False
    
    def exists(self, key: str) -> bool:
        """Vérifie si une clé existe."""
        value = self.get(key)
        return value is not None
    
    def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """Incrémente une valeur."""
        current = self.get(key)
        
        if current is None:
            try:
                current = 0
            except (TypeError, ValueError):
                return None
        
        try:
            new_value = int(current) + amount
            self.set(key, new_value)
            return new_value
        except (TypeError, ValueError):
            return None
    
    def decr(self, key: str, amount: int = 1) -> Optional[int]:
        """Décrémente une valeur."""
        return self.incr(key, -amount)
    
    def expire(self, key: str, seconds: int) -> bool:
        """Définit un TTL."""
        if key not in self._cache:
            return False
        
        import time
        _, _ = self._cache[key]
        self._cache[key] = (self._cache[key][0], time.time() + seconds)
        return True
    
    def ttl(self, key: str) -> Optional[int]:
        """Récupère le TTL."""
        if key not in self._cache:
            return None
        
        import time
        _, expiry = self._cache[key]
        
        if expiry is None:
            return -1
        
        remaining = int(expiry - time.time())
        return max(0, remaining)
    
    def delete_pattern(self, pattern: str) -> int:
        """Supprime les clés correspondant à un pattern."""
        # Simplification: pattern exact ou wildcard simple
        import fnmatch
        
        keys_to_delete = [
            k for k in self._cache.keys()
            if fnmatch.fnmatch(k, pattern)
        ]
        
        for key in keys_to_delete:
            del self._cache[key]
        
        return len(keys_to_delete)
    
    def health_check(self) -> dict:
        """Vérifie la santé du cache mémoire."""
        return {
            "status": "healthy",
            "cache_type": "memory",
            "key_count": len(self._cache),
        }
