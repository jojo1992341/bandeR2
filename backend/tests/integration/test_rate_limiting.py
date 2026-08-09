"""
Tests du rate limiting utilisateur/studio (CDC §10.1) — G-017.

Couvre :
- chaque catégorie (auth, upload, pipeline, export, public_api) : le dépassement
  renvoie 429 avec en-tête ``Retry-After`` ;
- isolation des compteurs entre deux studios ;
- politique de repli documentée en cas d'indisponibilité Redis (fail-open).

Harnais auto-contenu (SQLite + surcharge get_db + injection d'un rate limiter
mémoire). Le rate limiting est désactivé par défaut (RATE_LIMIT_ENABLED=False) ;
les tests injectent un ``RateLimiter`` mémoire activé.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth_handler import create_access_token
from app.core.database import get_db
from app.core.password import hash_password
from app.core.rate_limit import (
    DEFAULT_LIMITS,
    RateLimiter,
    reset_rate_limiter,
    set_rate_limiter,
)
from app.infrastructure.adapters.cache import MemoryCacheAdapter
from app.main import app
from app.models import Base, Studio, StudioMembership, User


_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Base.metadata.create_all(bind=_engine)
_TestingSessionLocal = sessionmaker(
    bind=_engine, autocommit=False, autoflush=False, expire_on_commit=False
)


def _override_get_db():
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _isolate():
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    # Rate limiter mémoire activé (quotas bas de DEFAULT_LIMITS pour des tests rapides)
    set_rate_limiter(
        RateLimiter(MemoryCacheAdapter(), enabled=True, fail_open=True)
    )
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
        reset_rate_limiter()


client = TestClient(app)


def _make_member(studio_name: str = "S"):
    db = _TestingSessionLocal()
    try:
        studio_id = uuid.uuid4()
        user_id = uuid.uuid4()
        email = f"u_{uuid.uuid4().hex[:8]}@x.com"
        db.add(Studio(id=studio_id, name=studio_name, plan="pro"))
        db.add(
            User(
                id=user_id,
                email=email,
                hashed_password=hash_password("Pass123!"),
                role="adaptateur",
                is_active=True,
            )
        )
        db.add(
            StudioMembership(
                id=uuid.uuid4(), studio_id=studio_id, user_id=user_id, role="adaptateur"
            )
        )
        db.commit()
        token = create_access_token(
            {"sub": str(user_id), "email": email, "role": "adaptateur", "tv": 0}
        )
        return {
            "studio_id": studio_id,
            "headers": {"Authorization": f"Bearer {token}"},
        }
    finally:
        db.close()


# ------------------------------------------------------------------
# 1. Chaque catégorie : dépassement -> 429 + Retry-After
# ------------------------------------------------------------------
class TestPerCategoryLimits:
    def test_auth_limit_429_retry_after(self):
        limit = DEFAULT_LIMITS["auth"][0]
        # On bombarde /auth/register (pas besoin d'utilisateur existant)
        codes = []
        last = None
        for _ in range(limit + 2):
            last = client.post(
                "/auth/register",
                json={"email": f"rate_{uuid.uuid4().hex[:6]}@x.com", "password": "Pass123!"},
            )
            codes.append(last.status_code)
        assert 429 in codes, f"Doit atteindre 429, codes: {codes}"
        assert last.status_code == 429
        assert "retry-after" in {k.lower() for k in last.headers.keys()}
        assert int(last.headers["Retry-After"]) >= 1
        assert last.json()["code"] == "rate_limited"

    def test_pipeline_limit_429_retry_after(self):
        member = _make_member()
        # /projects/{id}/pipeline/status -> 404 (pas de job) mais compte pour le quota
        limit = DEFAULT_LIMITS["pipeline"][0]
        codes = []
        last = None
        pid = uuid.uuid4()
        for _ in range(limit + 2):
            last = client.get(
                f"/projects/{pid}/pipeline/status", headers=member["headers"]
            )
            codes.append(last.status_code)
        assert 429 in codes, f"Doit atteindre 429, codes: {codes}"
        assert last.status_code == 429
        assert int(last.headers["Retry-After"]) >= 1

    def test_export_limit_429_retry_after(self):
        member = _make_member()
        limit = DEFAULT_LIMITS["export"][0]
        codes = []
        last = None
        pid = uuid.uuid4()
        for _ in range(limit + 2):
            last = client.post(f"/api/v1/projects/{pid}/exports", headers=member["headers"])
            codes.append(last.status_code)
        assert 429 in codes, f"Doit atteindre 429, codes: {codes}"
        assert last.status_code == 429


# ------------------------------------------------------------------
# 2. Isolation des compteurs entre studios (catégorie upload)
# ------------------------------------------------------------------
class TestStudioIsolation:
    def test_two_studios_independent_counters(self):
        a = _make_member("StudioA")
        b = _make_member("StudioB")
        limit = DEFAULT_LIMITS["upload"][0]
        # Studio A épuise son quota upload via /projects/{id}/media/upload-url
        # (les requêtes échouent en 404 projet, mais incrémentent le compteur studio)
        codes_a = []
        pid_a = uuid.uuid4()
        for _ in range(limit + 1):
            r = client.post(
                f"/projects/{pid_a}/media/upload-url",
                headers=a["headers"],
                json={"filename": "f.mp4", "content_type": "video/mp4"},
            )
            codes_a.append(r.status_code)
        assert 429 in codes_a, "Studio A doit avoir épuisé son quota"
        # Studio B doit encore pouvoir requêter (compteur isolé)
        pid_b = uuid.uuid4()
        r_b = client.post(
            f"/projects/{pid_b}/media/upload-url",
            headers=b["headers"],
            json={"filename": "f.mp4", "content_type": "video/mp4"},
        )
        assert r_b.status_code != 429, (
            f"Studio B ne doit pas être limité par la consommation de A: {r_b.status_code}"
        )


# ------------------------------------------------------------------
# 3. Politique de repli Redis indisponible (fail-open)
# ------------------------------------------------------------------
class _BrokenCache(MemoryCacheAdapter):
    """Cache qui simule une indisponibilité Redis (incr lève)."""

    def incr(self, key, amount=1):
        raise ConnectionError("Redis unavailable")

    def ttl(self, key):
        raise ConnectionError("Redis unavailable")


class TestRedisFallback:
    def test_fail_open_when_redis_down(self):
        # fail_open=True (défaut) -> la requête est autorisée malgré l'erreur cache
        set_rate_limiter(
            RateLimiter(_BrokenCache(), enabled=True, fail_open=True)
        )
        member = _make_member()
        pid = uuid.uuid4()
        codes = []
        for _ in range(DEFAULT_LIMITS["pipeline"][0] + 3):
            r = client.get(
                f"/projects/{pid}/pipeline/status", headers=member["headers"]
            )
            codes.append(r.status_code)
        # Aucun 429 : fail-open autorise tout
        assert 429 not in codes, f"Fail-open ne doit pas limiter: {codes}"

    def test_fail_closed_when_redis_down(self):
        # fail_open=False -> toute requête est refusée (sécurité)
        set_rate_limiter(
            RateLimiter(_BrokenCache(), enabled=True, fail_open=False)
        )
        member = _make_member()
        pid = uuid.uuid4()
        r = client.get(
            f"/projects/{pid}/pipeline/status", headers=member["headers"]
        )
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) >= 1

    def test_disabled_is_noop(self):
        # RATE_LIMIT_ENABLED=False -> aucune limitation
        set_rate_limiter(
            RateLimiter(MemoryCacheAdapter(), enabled=False, fail_open=True)
        )
        member = _make_member()
        pid = uuid.uuid4()
        codes = []
        for _ in range(DEFAULT_LIMITS["pipeline"][0] + 5):
            r = client.get(
                f"/projects/{pid}/pipeline/status", headers=member["headers"]
            )
            codes.append(r.status_code)
        assert 429 not in codes
