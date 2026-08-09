"""
Adaptateur HTTP Client (§6.2 CDC)

Implémente HttpClientPort et WebhookSenderPort en utilisant httpx.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

import httpx

from app.infrastructure.ports.http import HttpClientPort, WebhookSenderPort


class HttpAdapter(HttpClientPort):
    """
    Adaptateur HTTP utilisant httpx (async).
    
    Implémente HttpClientPort pour les requêtes HTTP.
    """
    
    def __init__(self, base_url: Optional[str] = None, timeout: int = 30):
        """
        Initialise l'adaptateur HTTP.
        
        Args:
            base_url: URL de base (optionnel).
            timeout: Timeout par défaut en secondes.
        """
        self._base_url = base_url
        self._timeout = timeout
        self._client: Optional[httpx.Client] = None
    
    @property
    def client(self) -> httpx.Client:
        """Retourne le client HTTP (lazy initialization)."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._client
    
    def _handle_response(self, response: httpx.Response) -> dict:
        """Traite la réponse HTTP."""
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            body = response.text
        
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "error": None,
        }
    
    def get(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        timeout: int = 30,
    ) -> dict:
        """Effectue une requête GET."""
        try:
            response = self.client.get(
                url,
                headers=headers,
                params=params,
                timeout=timeout,
            )
            return self._handle_response(response)
        except Exception as e:
            return {
                "status_code": None,
                "headers": {},
                "body": None,
                "error": str(e),
            }
    
    def post(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """Effectue une requête POST."""
        try:
            response = self.client.post(
                url,
                headers=headers,
                content=data,
                json=json,
                timeout=timeout,
            )
            return self._handle_response(response)
        except Exception as e:
            return {
                "status_code": None,
                "headers": {},
                "body": None,
                "error": str(e),
            }
    
    def put(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """Effectue une requête PUT."""
        try:
            response = self.client.put(
                url,
                headers=headers,
                content=data,
                json=json,
                timeout=timeout,
            )
            return self._handle_response(response)
        except Exception as e:
            return {
                "status_code": None,
                "headers": {},
                "body": None,
                "error": str(e),
            }
    
    def delete(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: int = 30,
    ) -> dict:
        """Effectue une requête DELETE."""
        try:
            response = self.client.delete(
                url,
                headers=headers,
                timeout=timeout,
            )
            return self._handle_response(response)
        except Exception as e:
            return {
                "status_code": None,
                "headers": {},
                "body": None,
                "error": str(e),
            }
    
    def patch(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """Effectue une requête PATCH."""
        try:
            response = self.client.patch(
                url,
                headers=headers,
                content=data,
                json=json,
                timeout=timeout,
            )
            return self._handle_response(response)
        except Exception as e:
            return {
                "status_code": None,
                "headers": {},
                "body": None,
                "error": str(e),
            }
    
    def health_check(self) -> dict:
        """Vérifie la santé du client HTTP."""
        return {
            "status": "healthy",
            "http_type": "httpx",
            "base_url": self._base_url,
        }


class WebhookAdapter(WebhookSenderPort):
    """
    Adaptateur pour l'envoi de webhooks.
    
    Implémente WebhookSenderPort avec signature HMAC.
    """
    
    def __init__(self, http_adapter: Optional[HttpAdapter] = None):
        """
        Initialise l'adaptateur webhook.
        
        Args:
            http_adapter: Adaptateur HTTP à utiliser (défaut: nouveau).
        """
        self._http = http_adapter or HttpAdapter()
    
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
            secret: Secret pour la signature HMAC.
            event_type: Type d'événement.
            idempotency_key: Clé d'idempotence.
        """
        # Préparer les headers
        headers = {"Content-Type": "application/json"}
        
        if event_type:
            headers["X-Event-Type"] = event_type
        
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        
        # Signer le payload si secret fourni
        payload_bytes = json.dumps(payload).encode("utf-8")
        
        if secret:
            signature = hmac.new(
                secret.encode("utf-8"),
                payload_bytes,
                hashlib.sha256,
            ).hexdigest()
            headers["X-RythmoAI-Signature"] = f"sha256={signature}"
        
        # Envoyer la requête
        response = self._http.post(
            url,
            headers=headers,
            json=payload,
        )
        
        return {
            "success": response["status_code"] is not None and 200 <= response["status_code"] < 300,
            "status_code": response["status_code"],
            "response": response["body"],
            "error": response["error"],
        }
    
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
        """
        if not signature.startswith(f"{algorithm}="):
            return False
        
        expected_signature = signature.split("=", 1)[1]
        
        actual_signature = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, actual_signature)
    
    def health_check(self) -> dict:
        """Vérifie la santé de l'adaptateur webhook."""
        return {
            "status": "healthy",
            "webhook_type": "http",
        }


class MemoryHttpAdapter(HttpClientPort):
    """
    Adaptateur HTTP en mémoire (pour les tests).
    
    Simule les requêtes HTTP sans faire d'appels réseau.
    """
    
    def __init__(self):
        """Initialise l'adaptateur mémoire."""
        self.requests: list[dict] = []
        self._mock_responses: dict[str, dict] = {}
    
    def mock_response(self, url: str, method: str, response: dict) -> None:
        """Configure une réponse simulée pour une URL/méthode."""
        key = f"{method}:{url}"
        self._mock_responses[key] = response
    
    def get(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        timeout: int = 30,
    ) -> dict:
        """Simule une requête GET."""
        request = {
            "method": "GET",
            "url": url,
            "headers": headers or {},
            "params": params,
        }
        self.requests.append(request)
        
        key = f"GET:{url}"
        return self._mock_responses.get(key, {
            "status_code": 200,
            "headers": {},
            "body": {},
            "error": None,
        })
    
    def post(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """Simule une requête POST."""
        request = {
            "method": "POST",
            "url": url,
            "headers": headers or {},
            "data": data,
            "json": json,
        }
        self.requests.append(request)
        
        key = f"POST:{url}"
        return self._mock_responses.get(key, {
            "status_code": 200,
            "headers": {},
            "body": {},
            "error": None,
        })
    
    def put(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """Simule une requête PUT."""
        request = {
            "method": "PUT",
            "url": url,
            "headers": headers or {},
            "data": data,
            "json": json,
        }
        self.requests.append(request)
        
        key = f"PUT:{url}"
        return self._mock_responses.get(key, {
            "status_code": 200,
            "headers": {},
            "body": {},
            "error": None,
        })
    
    def delete(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: int = 30,
    ) -> dict:
        """Simule une requête DELETE."""
        request = {
            "method": "DELETE",
            "url": url,
            "headers": headers or {},
        }
        self.requests.append(request)
        
        key = f"DELETE:{url}"
        return self._mock_responses.get(key, {
            "status_code": 200,
            "headers": {},
            "body": {},
            "error": None,
        })
    
    def patch(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """Simule une requête PATCH."""
        request = {
            "method": "PATCH",
            "url": url,
            "headers": headers or {},
            "data": data,
            "json": json,
        }
        self.requests.append(request)
        
        key = f"PATCH:{url}"
        return self._mock_responses.get(key, {
            "status_code": 200,
            "headers": {},
            "body": {},
            "error": None,
        })
    
    def health_check(self) -> dict:
        """Vérifie la santé de l'adaptateur mémoire."""
        return {
            "status": "healthy",
            "http_type": "memory",
            "request_count": len(self.requests),
        }
    
    def get_requests(self) -> list[dict]:
        """Retourne les requêtes enregistrées."""
        return self.requests.copy()
    
    def clear(self) -> None:
        """Efface les requêtes enregistrées."""
        self.requests.clear()
        self._mock_responses.clear()
