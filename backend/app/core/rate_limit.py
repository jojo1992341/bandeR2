"""
Rate limiting utilisateur/studio (CDC §10.1) — G-017.

Quotas Redis distincts par catégorie, appliqués aux endpoints sensibles/coûteux :
- ``auth``       : login/register (par IP — anti brute-force)
- ``upload``     : import média (par studio)
- ``pipeline``   : lancement/statut pipeline IA (par studio)
- ``export``     : génération d'exports (par studio)
- ``public_api`` : API publique / webhooks (par clé API ou IP)

Compteurs à fenêtre fixe : ``incr`` atomique + TTL sur le premier incrément.

Politique de repli si Redis est indisponible (``RATE_LIMIT_FAIL_OPEN``) :
- **fail-open** (défaut, disponibilité) : la requête est autorisée et l'échec
  est journalisé — on préfère laisser passer des utilisateurs légitimes plutôt
  que de bloquer toute l'API ;
- **fail-closed** : la requête est refusée (429) par sécurité.

Le rate limiting est piloté par le feature-flag ``RATE_LIMIT_ENABLED`` (défaut
désactivé pour les tests) — il est sans effet hors activation.
"""

from __future__ import annotations

import logging
import uuid
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rbac import get_current_user_payload, get_optional_user_payload
from app.infrastructure.adapters.cache import MemoryCacheAdapter
from app.infrastructure.ports.cache import CachePort

logger = logging.getLogger("rythmoai")


# category -> (limite, fenêtre en secondes)
DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "auth": (5, 60),
    "upload": (4, 60),
    "pipeline": (3, 60),
    "export": (4, 60),
    "public_api": (6, 60),
}


class RateLimiter:
    """Compteur de quota à fenêtre fixe sur un CachePort (Redis en prod)."""

    def __init__(
        self,
        cache: CachePort,
        limits: Optional[dict[str, tuple[int, int]]] = None,
        fail_open: bool = True,
        enabled: bool = True,
    ):
        self.cache = cache
        self.limits = limits or dict(DEFAULT_LIMITS)
        self.fail_open = fail_open
        self.enabled = enabled

    def check(self, category: str, identifier: str) -> tuple[bool, int]:
        """
        Vérifie le quota ``category`` pour ``identifier``.

        Returns:
            (allowed, retry_after_seconds). ``retry_after`` vaut 0 si autorisé.
        """
        if not self.enabled:
            return True, 0
        cfg = self.limits.get(category)
        if cfg is None:
            return True, 0
        limit, window = cfg
        key = f"ratelimit:{category}:{identifier}"
        try:
            count = self.cache.incr(key)
            if count is None:
                return self._fallback(window)
            if count == 1:
                self.cache.expire(key, window)
            if count > limit:
                ttl = self.cache.ttl(key)
                retry_after = (
                    ttl if (ttl is not None and ttl >= 0) else window
                )
                return False, max(1, retry_after)
            return True, 0
        except Exception as exc:
            logger.warning("Rate limit cache error (%s): %s", category, exc)
            return self._fallback(window)

    def _fallback(self, window: int) -> tuple[bool, int]:
        if self.fail_open:
            return True, 0
        return False, window


# ------------------------------------------------------------------
# Singleton injectable (prod: RedisCacheAdapter ; tests: injection mémoire)
# ------------------------------------------------------------------
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        settings = get_settings()
        # En l'absence de Redis, l'adaptateur Redis lèvera/l'attrapera et le
        # fallback s'appliquera ; on l'initialise paresseusement.
        from app.infrastructure.drivers.cache_driver import get_cache_adapter

        cache = get_cache_adapter()
        _rate_limiter = RateLimiter(
            cache=cache,
            fail_open=getattr(settings, "RATE_LIMIT_FAIL_OPEN", True),
            enabled=getattr(settings, "RATE_LIMIT_ENABLED", False),
        )
    return _rate_limiter


def set_rate_limiter(limiter: Optional[RateLimiter]) -> None:
    """Injecte un rate limiter (pour les tests)."""
    global _rate_limiter
    _rate_limiter = limiter


def reset_rate_limiter() -> None:
    """Réinitialise le singleton (entre tests)."""
    global _rate_limiter
    _rate_limiter = None


# ------------------------------------------------------------------
# Helpers d'identification
# ------------------------------------------------------------------
def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _user_studio_id(db: Session, user_id: uuid.UUID) -> str:
    from app.models import StudioMembership

    m = (
        db.query(StudioMembership)
        .filter(StudioMembership.user_id == user_id)
        .first()
    )
    return str(m.studio_id) if m else f"user:{user_id}"


def _deny(retry_after: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Limite de taux dépassée (rate limit exceeded)",
        headers={"Retry-After": str(retry_after)},
    )


# ------------------------------------------------------------------
# Dépendances FastAPI
# ------------------------------------------------------------------
def auth_rate_limit(request: Request) -> None:
    limiter = get_rate_limiter()
    allowed, retry_after = limiter.check("auth", _client_ip(request))
    if not allowed:
        _deny(retry_after)


def _studio_rate_limit_factory(category: str):
    def dep(
        payload: dict = Depends(get_current_user_payload),
        db: Session = Depends(get_db),
    ) -> None:
        limiter = get_rate_limiter()
        user_id = uuid.UUID(payload["sub"])
        allowed, retry_after = limiter.check(category, _user_studio_id(db, user_id))
        if not allowed:
            _deny(retry_after)

    return dep


def upload_rate_limit_dep(
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
) -> None:
    """Quota d'import média (par studio)."""
    limiter = get_rate_limiter()
    user_id = uuid.UUID(payload["sub"])
    allowed, retry_after = limiter.check("upload", _user_studio_id(db, user_id))
    if not allowed:
        _deny(retry_after)


def pipeline_rate_limit_dep(
    request: Request,
    payload: dict = Depends(get_optional_user_payload),
    db: Session = Depends(get_db),
) -> None:
    """Quota pipeline IA (par studio si authentifié, sinon par IP)."""
    limiter = get_rate_limiter()
    if payload and payload.get("sub"):
        ident = _user_studio_id(db, uuid.UUID(payload["sub"]))
    else:
        ident = "ip:" + _client_ip(request)
    allowed, retry_after = limiter.check("pipeline", ident)
    if not allowed:
        _deny(retry_after)


def export_rate_limit_dep(
    request: Request,
    payload: dict = Depends(get_optional_user_payload),
    db: Session = Depends(get_db),
) -> None:
    """Quota d'export (par studio si authentifié, sinon par IP)."""
    limiter = get_rate_limiter()
    if payload and payload.get("sub"):
        ident = _user_studio_id(db, uuid.UUID(payload["sub"]))
    else:
        ident = "ip:" + _client_ip(request)
    allowed, retry_after = limiter.check("export", ident)
    if not allowed:
        _deny(retry_after)


def public_api_rate_limit(request: Request) -> None:
    limiter = get_rate_limiter()
    ident = request.headers.get("x-api-key") or _client_ip(request)
    allowed, retry_after = limiter.check("public_api", ident)
    if not allowed:
        _deny(retry_after)
