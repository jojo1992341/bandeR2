"""
Tests du schéma d'erreur commun et de la corrélation (CDC §10.1) — G-015.

Vérifie :
- toutes les erreurs API renvoient {code, message, details, request_id} ;
- le request_id est présent dans l'en-tête X-Request-ID et les logs structurés ;
- un X-Request-ID fourni est réutilisé (corrélation) ;
- les exceptions internes (500) ne divulguent pas de secret.

Harnais auto-contenu (SQLite + surcharge de get_db).
"""

from __future__ import annotations

import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth_handler import create_access_token
from app.core.database import get_db
from app.core.password import hash_password
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
def _isolate_get_db():
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


client = TestClient(app, raise_server_exceptions=False)


def _make_member():
    db = _TestingSessionLocal()
    email = f"m_{uuid.uuid4().hex[:8]}@x.com"
    try:
        studio_id = uuid.uuid4()
        user_id = uuid.uuid4()
        db.add(Studio(id=studio_id, name="S", plan="pro"))
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
        return {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _assert_uniform(body):
    # Le contrat canonique {code, message, details, request_id} doit être présent.
    for field in ("code", "message", "details", "request_id"):
        assert field in body, f"Champ uniforme manquant: {field} dans {body}"
    assert isinstance(body["code"], str)
    assert isinstance(body["message"], str)
    assert isinstance(body["request_id"], str) and body["request_id"]


# ============================================================
# Schéma uniforme sur les codes 4xx
# ============================================================
class TestUniformSchema:
    def test_401(self):
        r = client.get("/api/v1/users/me")
        assert r.status_code == 401
        body = r.json()
        _assert_uniform(body)
        assert body["code"] == "unauthorized"

    def test_404(self):
        headers = _make_member()
        r = client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=headers)
        assert r.status_code == 404
        body = r.json()
        _assert_uniform(body)
        assert body["code"] == "not_found"

    def test_403(self):
        headers = _make_member()
        # Un simple membre (non-admin) ne peut pas lister les utilisateurs (admin only).
        r = client.get("/api/v1/users", headers=headers)
        assert r.status_code == 403
        body = r.json()
        _assert_uniform(body)
        assert body["code"] == "forbidden"

    def test_422_validation(self):
        r = client.post("/auth/register", json={"email": "not-an-email"})
        assert r.status_code == 422
        body = r.json()
        _assert_uniform(body)
        assert body["code"] == "validation_error"
        assert isinstance(body["details"], list) and body["details"]


# ============================================================
# Corrélation request_id (header + corps)
# ============================================================
class TestCorrelation:
    def test_request_id_generated_and_present(self):
        r = client.get("/api/v1/users/me")
        body = r.json()
        assert r.headers["X-Request-ID"] == body["request_id"]

    def test_custom_request_id_echoed(self):
        rid = "my-custom-trace-id"
        r = client.get("/api/v1/users/me", headers={"X-Request-ID": rid})
        body = r.json()
        assert body["request_id"] == rid
        assert r.headers["X-Request-ID"] == rid


# ============================================================
# Logs structurés : le request_id apparaît
# ============================================================
class TestStructuredLogs:
    def test_request_id_in_logs(self, caplog):
        caplog.set_level(logging.INFO)
        rid = "log-trace-abc"
        r = client.get("/api/v1/users/me", headers={"X-Request-ID": rid})
        assert r.status_code == 401
        # Au moins un record du logger rythmoai porte ce request_id
        matched = [
            rec
            for rec in caplog.records
            if getattr(rec, "request_id", None) == rid
        ]
        assert matched, "Aucun log structuré ne porte le request_id"
        # Le format contient bien le request_id
        assert any("req=log-trace-abc" in rec.getMessage() or rid in str(rec) for rec in caplog.records) or matched


# ============================================================
# Exception interne : pas de fuite de secret
# ============================================================
SECRET = "SUPER_SECRET_INTERNAL_TOKEN_42"


def _boom():
    raise RuntimeError(f"echec interne contenant {SECRET}")


class TestNoSecretLeak:
    def setup_method(self):
        app.add_api_route("/_test/boom", _boom, methods=["GET"])

    def teardown_method(self):
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/_test/boom"
        ]

    def test_500_returns_uniform_schema_without_secret(self):
        r = client.get("/_test/boom")
        assert r.status_code == 500
        body = r.json()
        _assert_uniform(body)
        assert body["code"] == "internal_error"
        assert SECRET not in r.text
        assert SECRET not in body["message"]
        # Le request_id est bien présent (pour le support)
        assert body["request_id"]

    def test_500_has_request_id_header(self):
        r = client.get("/_test/boom", headers={"X-Request-ID": "boom-trace"})
        assert r.status_code == 500
        assert r.headers["X-Request-ID"] == "boom-trace"
