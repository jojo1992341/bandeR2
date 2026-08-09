"""
Driver HTTP Client (§6.2 CDC)

Fabrique pour obtenir l'adaptateur HTTP approprié selon l'environnement.
"""

from __future__ import annotations

from typing import Optional

from app.infrastructure.adapters.http import (
    HttpAdapter,
    WebhookAdapter,
    MemoryHttpAdapter,
    HttpClientPort,
    WebhookSenderPort,
)


def get_http_adapter(
    for_test: bool = False,
    base_url: Optional[str] = None,
    timeout: int = 30,
) -> HttpClientPort:
    """
    Retourne l'adaptateur HTTP approprié.
    
    Args:
        for_test: Si True, retourne un adaptateur mémoire.
        base_url: URL de base.
        timeout: Timeout par défaut.
        
    Returns:
        Adaptateur HttpClientPort.
    """
    if for_test:
        return MemoryHttpAdapter()
    
    return HttpAdapter(base_url=base_url, timeout=timeout)


def get_webhook_adapter(
    http_adapter: Optional[HttpAdapter] = None,
) -> WebhookSenderPort:
    """
    Retourne l'adaptateur webhook.
    
    Args:
        http_adapter: Adaptateur HTTP à utiliser.
        
    Returns:
        Adaptateur WebhookSenderPort.
    """
    return WebhookAdapter(http_adapter=http_adapter)


def get_memory_http() -> MemoryHttpAdapter:
    """Retourne l'adaptateur mémoire pour les tests."""
    return MemoryHttpAdapter()


def get_memory_webhook() -> WebhookSenderPort:
    """Retourne l'adaptateur webhook mémoire pour les tests."""
    http_adapter = MemoryHttpAdapter()
    return WebhookAdapter(http_adapter=http_adapter)
