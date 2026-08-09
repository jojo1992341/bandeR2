"""
Driver de Cache (§6.2 CDC)

Fabrique pour obtenir l'adaptateur de cache approprié selon l'environnement.
"""

from __future__ import annotations

from typing import Optional

from app.core.config import get_settings
from app.infrastructure.adapters.cache import (
    RedisCacheAdapter,
    MemoryCacheAdapter,
    CachePort,
)


def get_cache_adapter(
    for_test: bool = False,
    settings: Optional[Any] = None,
) -> CachePort:
    """
    Retourne l'adaptateur de cache approprié.
    
    Args:
        for_test: Si True, retourne un adaptateur mémoire.
        settings: Configuration personnalisée.
        
    Returns:
        Adaptateur CachePort.
    """
    if for_test:
        return MemoryCacheAdapter()
    
    return RedisCacheAdapter(settings=settings)


def get_redis_cache() -> RedisCacheAdapter:
    """Retourne l'adaptateur Redis pour la production."""
    return RedisCacheAdapter(settings=get_settings())


def get_memory_cache() -> MemoryCacheAdapter:
    """Retourne l'adaptateur mémoire pour les tests."""
    return MemoryCacheAdapter()
