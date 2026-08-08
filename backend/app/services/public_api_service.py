"""
Service de l'API publique §25.4 — gestion des clés API, des abonnements
webhook et de la livraison signée des notifications.

Sécurité :
  * les clés API sont stockées uniquement sous forme de SHA-256 (jamais en clair) ;
  * chaque livraison webhook est signée ``X-RythmoAI-Signature: sha256=<hex>``,
    calculée comme HMAC-SHA256 du corps UTF-8 avec le secret de l'endpoint ;
  * un en-tête ``X-RythmoAI-Timestamp`` est inclus pour permettre au récepteur
    de rejeter les rejeux (tolérance recommandée : 5 minutes) ;
  * les URL webhook sont validées (schéma http/https, pas d'adresses de
    metadata cloud, hôte non vide) pour prévenir le SSRF (§15.7).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.models import ApiKey, Project, Studio, WebhookDelivery, WebhookEndpoint

logger = logging.getLogger("rythmoai")

# Événements webhook supportés par l'API publique (§25.4)
SUPPORTED_EVENTS = (
    "pipeline.completed",
    "pipeline.failed",
    "export.completed",
)

# Scopes disponibles pour une clé API
SUPPORTED_SCOPES = (
    "project:read",
    "project:write",
    "export:write",
    "webhook:write",
)

DEFAULT_SCOPES = ["project:read", "project:write", "export:write"]


# ─────────────────────────────────────────────────────────────────────────────
# Clés API
# ─────────────────────────────────────────────────────────────────────────────
def generate_api_key(prefix: str = "ryth") -> Tuple[str, str, str]:
    """Génère une clé API opaque.

    Retourne ``(key_full, key_prefix, key_hash)``. Seul ``key_full`` est
    renvoyé une seule fois, à présenter au client.
    """
    token = secrets.token_urlsafe(32)
    full = f"{prefix}_{token}"
    key_prefix = full[: len(prefix) + 6]
    key_hash = hash_api_key(full)
    return full, key_prefix, key_hash


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def create_api_key(
    db: Session,
    studio_id,
    name: str,
    scopes: Optional[Iterable[str]] = None,
    created_by: Optional[str] = None,
    expires_at: Optional[datetime] = None,
) -> Tuple[ApiKey, str]:
    """Crée une clé API et la persiste. Retourne (objet, clé en clair)."""
    scopes = list(scopes) if scopes else list(DEFAULT_SCOPES)
    invalid = [s for s in scopes if s not in SUPPORTED_SCOPES]
    if invalid:
        raise ValueError(f"Scopes non supportés: {', '.join(invalid)}")
    full, prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        studio_id=studio_id,
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=scopes,
        created_by=created_by,
        is_active=True,
        expires_at=expires_at,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key, full


def get_api_key_by_hash(db: Session, api_key: str) -> Optional[ApiKey]:
    return db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(api_key)).first()


def is_api_key_valid(
    api_key: ApiKey, required_scopes: Optional[Iterable[str]] = None
) -> bool:
    if not api_key or not api_key.is_active:
        return False
    if api_key.expires_at:
        if datetime.now(timezone.utc) > api_key.expires_at.replace(tzinfo=timezone.utc):
            return False
    if required_scopes:
        granted = set(api_key.scopes or [])
        if not set(required_scopes).issubset(granted):
            return False
    return True


def touch_api_key_used(db: Session, api_key: ApiKey) -> None:
    try:
        api_key.last_used_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:  # pragma: no cover - non bloquant
        db.rollback()


# ─────────────────────────────────────────────────────────────────────────────
# Validation d'URL webhook (anti-SSRF §15.7)
# ─────────────────────────────────────────────────────────────────────────────
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),  # metadata cloud / link-local
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
)


def validate_webhook_url(url: str, *, allow_loopback: bool = False) -> str:
    """Valide une URL webhook. Lève ``ValueError`` si invalide (SSRF/schéma)."""
    if not url or not isinstance(url, str):
        raise ValueError("URL requise")
    if len(url) > 2000:
        raise ValueError("URL trop longue")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Schéma non supporté (http/https attendus)")
    host = parsed.hostname
    if not host:
        raise ValueError("Hôte manquant")
    if parsed.username or parsed.password:
        raise ValueError("Identifiants interdits dans l'URL webhook")

    # Résolution DNS et contrôle des adresses privées
    try:
        infos = socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror as exc:
        raise ValueError(f"Résolution DNS impossible: {exc}") from exc

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_loopback:
            if allow_loopback:
                continue
            raise ValueError("Adresse loopback interdite en production")
        if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError(f"Adresse réseau interdite: {ip}")
        for net in _BLOCKED_NETWORKS:
            if ip in net and not (
                allow_loopback and net == ipaddress.ip_network("127.0.0.0/8")
            ):
                raise ValueError(f"Adresse réseau privé/interdite: {ip}")
    return url


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints webhook
# ─────────────────────────────────────────────────────────────────────────────
def generate_webhook_secret() -> str:
    return secrets.token_hex(32)


def create_webhook_endpoint(
    db: Session,
    studio_id,
    url: str,
    events: Iterable[str],
    *,
    api_key_id=None,
    description: Optional[str] = None,
    secret: Optional[str] = None,
    allow_loopback: bool = False,
) -> WebhookEndpoint:
    events = list(events)
    invalid = [e for e in events if e not in SUPPORTED_EVENTS]
    if invalid:
        raise ValueError(f"Événements non supportés: {', '.join(invalid)}")
    if not events:
        raise ValueError("Au moins un événement est requis")
    url = validate_webhook_url(url, allow_loopback=allow_loopback)
    endpoint = WebhookEndpoint(
        studio_id=studio_id,
        api_key_id=api_key_id,
        url=url,
        secret=secret or generate_webhook_secret(),
        description=description,
        events=events,
        is_active=True,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return endpoint


# ─────────────────────────────────────────────────────────────────────────────
# Signature et livraison
# ─────────────────────────────────────────────────────────────────────────────
def sign_payload(secret: str, body: bytes, timestamp: int) -> str:
    signed = f"{timestamp}.".encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def _redeliver_delay(attempts: int) -> int:
    # Backoff exponentiel : 30s, 1m, 5m, 30m, 2h (capé)
    delays = [30, 60, 300, 1800, 7200]
    return delays[min(attempts, len(delays) - 1)]


def deliver_webhook(
    db: Session,
    endpoint: WebhookEndpoint,
    event: str,
    data: Dict[str, Any],
    *,
    timeout: float = 5.0,
    max_attempts: int = 5,
) -> WebhookDelivery:
    """Tente une livraison immédiate, persiste le résultat et planifie un retry.

    Retourne l'enregistrement ``WebhookDelivery``. En cas d'échec transient,
    ``next_retry_at`` est positionné avec un backoff exponentiel.
    """
    payload = {
        "id": str(__import__("uuid").uuid4()),
        "event": event,
        "created": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    delivery = WebhookDelivery(
        endpoint_id=endpoint.id,
        event=event,
        payload=payload,
        status="pending",
        attempts=0,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    return _attempt_delivery(
        db, delivery, endpoint, body, timeout=timeout, max_attempts=max_attempts
    )


def _attempt_delivery(
    db: Session,
    delivery: WebhookDelivery,
    endpoint: WebhookEndpoint,
    body: bytes,
    *,
    timeout: float,
    max_attempts: int,
) -> WebhookDelivery:
    timestamp = int(datetime.now(timezone.utc).timestamp())
    signature = sign_payload(endpoint.secret, body, timestamp)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "RythmoAI-Webhook/1.0",
        "X-RythmoAI-Event": delivery.event,
        "X-RythmoAI-Delivery": str(delivery.id),
        "X-RythmoAI-Timestamp": str(timestamp),
        "X-RythmoAI-Signature": f"sha256={signature}",
    }
    delivery.attempts = (delivery.attempts or 0) + 1
    try:
        resp = requests.post(
            endpoint.url,
            data=body,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
        delivery.response_status_code = int(resp.status_code)
        # On stocke un extrait de la réponse (1 Ko max)
        delivery.response_body = (resp.text or "")[:1024]
        if 200 <= resp.status_code < 300:
            delivery.status = "delivered"
            delivery.delivered_at = datetime.now(timezone.utc)
            delivery.next_retry_at = None
        else:
            delivery.status = "failed"
            delivery.error = f"HTTP {resp.status_code}"
            delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(
                seconds=_redeliver_delay(delivery.attempts)
            )
    except requests.RequestException as exc:
        delivery.status = "failed"
        delivery.error = str(exc)[:1024]
        delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(
            seconds=_redeliver_delay(delivery.attempts)
        )

    if delivery.attempts >= max_attempts and delivery.status == "failed":
        delivery.next_retry_at = None  # abandon

    db.commit()
    db.refresh(delivery)
    return delivery


def dispatch_event(
    db: Session,
    studio_id,
    event: str,
    data: Dict[str, Any],
    *,
    timeout: float = 5.0,
) -> List[WebhookDelivery]:
    """Notifie tous les endpoints actifs du studio abonnés à ``event``.

    Les échecs sont isolés (un endpoint défaillant n'impacte pas les autres).
    """
    endpoints = (
        db.query(WebhookEndpoint)
        .filter(
            WebhookEndpoint.studio_id == studio_id,
            WebhookEndpoint.is_active.is_(True),
        )
        .all()
    )
    deliveries: List[WebhookDelivery] = []
    for endpoint in endpoints:
        events = endpoint.events or []
        if event not in events and "*" not in events:
            continue
        try:
            deliveries.append(
                deliver_webhook(db, endpoint, event, data, timeout=timeout)
            )
        except Exception as exc:  # pragma: no cover - isolation
            logger.warning("dispatch_event endpoint=%s error=%s", endpoint.id, exc)
    return deliveries


# ─────────────────────────────────────────────────────────────────────────────
# Vérification de signature côté récepteur (utilitaire pour clients/intégrations)
# ─────────────────────────────────────────────────────────────────────────────
def verify_signature(
    secret: str,
    body: bytes,
    timestamp: str,
    signature: str,
    *,
    max_skew_seconds: int = 300,
) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - ts) > max_skew_seconds:
        return False
    expected = sign_payload(secret, body, ts)
    provided = signature.replace("sha256=", "").strip()
    return hmac.compare_digest(expected, provided)
