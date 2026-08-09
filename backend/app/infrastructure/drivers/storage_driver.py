"""
Driver de Stockage (§6.2 CDC)

Fabrique pour obtenir l'adaptateur de stockage approprié selon l'environnement.
"""

from __future__ import annotations

from typing import Optional

from app.core.config import get_settings
from app.infrastructure.adapters.storage import (
    S3StorageAdapter,
    MemoryStorageAdapter,
    StoragePort,
)


def get_storage_adapter(
    for_test: bool = False,
    settings: Optional[Any] = None,
) -> StoragePort:
    """
    Retourne l'adaptateur de stockage approprié.
    
    Args:
        for_test: Si True, retourne un adaptateur mémoire.
        settings: Configuration personnalisée.
        
    Returns:
        Adaptateur StoragePort.
    """
    if for_test:
        return MemoryStorageAdapter()
    
    return S3StorageAdapter(settings=settings)


def get_s3_storage() -> S3StorageAdapter:
    """Retourne l'adaptateur S3 pour la production."""
    return S3StorageAdapter(settings=get_settings())


def get_memory_storage() -> MemoryStorageAdapter:
    """Retourne l'adaptateur mémoire pour les tests."""
    return MemoryStorageAdapter()
