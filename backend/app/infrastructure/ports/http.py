"""
Port HTTP Client (§6.2 CDC)

Interface stable pour les appels HTTP externes (webhooks, API tierces).
Les adaptateurs (requests, httpx, mémoire pour tests) doivent implémenter
cette interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class HttpClientPort(ABC):
    """
    Interface pour le client HTTP.
    
    Permet de faire des requêtes HTTP de manière agnostique par rapport
    à la bibliothèque utilisée (requests, httpx, aiohttp, etc.).
    """
    
    @abstractmethod
    def get(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        timeout: int = 30,
    ) -> dict:
        """
        Effectue une requête GET.
        
        Args:
            url: URL de la requête.
            headers: En-têtes HTTP.
            params: Paramètres de requête (query string).
            timeout: Timeout en secondes.
            
        Returns:
            Dictionnaire avec 'status_code', 'headers', 'body', 'error'.
        """
        ...
    
    @abstractmethod
    def post(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """
        Effectue une requête POST.
        
        Args:
            url: URL de la requête.
            headers: En-têtes HTTP.
            data: Données à envoyer (form-encoded).
            json: Données JSON à envoyer.
            timeout: Timeout en secondes.
            
        Returns:
            Dictionnaire avec 'status_code', 'headers', 'body', 'error'.
        """
        ...
    
    @abstractmethod
    def put(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """
        Effectue une requête PUT.
        
        Args:
            url: URL de la requête.
            headers: En-têtes HTTP.
            data: Données à envoyer.
            json: Données JSON à envoyer.
            timeout: Timeout en secondes.
            
        Returns:
            Dictionnaire avec 'status_code', 'headers', 'body', 'error'.
        """
        ...
    
    @abstractmethod
    def delete(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: int = 30,
    ) -> dict:
        """
        Effectue une requête DELETE.
        
        Args:
            url: URL de la requête.
            headers: En-têtes HTTP.
            timeout: Timeout en secondes.
            
        Returns:
            Dictionnaire avec 'status_code', 'headers', 'body', 'error'.
        """
        ...
    
    @abstractmethod
    def patch(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """
        Effectue une requête PATCH.
        
        Args:
            url: URL de la requête.
            headers: En-têtes HTTP.
            data: Données à envoyer.
            json: Données JSON à envoyer.
            timeout: Timeout en secondes.
            
        Returns:
            Dictionnaire avec 'status_code', 'headers', 'body', 'error'.
        """
        ...
    
    @abstractmethod
    def health_check(self) -> dict:
        """
        Vérifie la santé du client HTTP.
        
        Returns:
            Dictionnaire avec le statut.
        """
        ...


class WebhookSenderPort(ABC):
    """
    Interface spécifique pour l'envoi de webhooks.
    
    Les webhooks nécessitent des fonctionnalités supplémentaires:
    - Signatures HMAC
    - Retry avec backoff
    - Tracking des livraisons
    """
    
    @abstractmethod
    def send_webhook(
        self,
        url: str,
        payload: dict,
        secret: Optional[str] = None,
        event_type: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """
        Envoie un webhook avec signature optionnelle.
        
        Args:
            url: URL du webhook.
            payload: Payload JSON à envoyer.
            secret: Secret pour la signature HMAC (optionnel).
            event_type: Type d'événement (pour l'en-tête X-Event-Type).
            idempotency_key: Clé d'idempotence (pour éviter les doubles).
            
        Returns:
            Dictionnaire avec 'success', 'status_code', 'response', 'error'.
        """
        ...
    
    @abstractmethod
    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        secret: str,
        algorithm: str = "sha256",
    ) -> bool:
        """
        Vérifie la signature d'un webhook entrant.
        
        Args:
            payload: Corps de la requête (brut).
            signature: Signature reçue (ex: "sha256=abc123...").
            secret: Secret partagé.
            algorithm: Algorithme de signature.
            
        Returns:
            True si la signature est valide.
        """
        ...
