"""
Driver d'Email (§6.2 CDC)

Fabrique pour obtenir l'adaptateur d'email approprié selon l'environnement.
"""

from __future__ import annotations

from typing import Optional

from app.core.config import get_settings
from app.infrastructure.adapters.email import (
    SmtpEmailAdapter,
    MemoryEmailAdapter,
    EmailPort,
)


def get_email_adapter(
    for_test: bool = False,
    settings: Optional[Any] = None,
) -> EmailPort:
    """
    Retourne l'adaptateur d'email approprié.
    
    Args:
        for_test: Si True, retourne un adaptateur mémoire.
        settings: Configuration personnalisée.
        
    Returns:
        Adaptateur EmailPort.
    """
    if for_test:
        return MemoryEmailAdapter()
    
    return SmtpEmailAdapter(settings=settings)


def get_smtp_email() -> SmtpEmailAdapter:
    """Retourne l'adaptateur SMTP pour la production."""
    return SmtpEmailAdapter(settings=get_settings())


def get_memory_email() -> MemoryEmailAdapter:
    """Retourne l'adaptateur mémoire pour les tests."""
    return MemoryEmailAdapter()
