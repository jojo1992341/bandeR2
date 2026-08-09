"""
Tests de la ressource Users (CDC §10.2 & §16.2) — G-012.

Couvre : profil, préférences exposées, permissions, désactivation, opérations
administratives, et **refus inter-studios** (anti-IDOR).

Harnais auto-contenu (moteur SQLite synchrone + surcharge de `get_db`).
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
from app.main import app
from app.models import Base, Studio, StudioMembership, User, UserPreferences


# ------------------------------------------------------------------
# Harnais
# ------------------------------------------------------------------
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


client = TestClient(app)


def _db():
    return _TestingSessionLocal()


def _clean():
    db = _db()
    try:
        for model in (UserPreferences, StudioMembership, User, Studio):
            db.query(model).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _make_user(
    email: str,
    *,
    studio_name: str,
    global_role: str = "adaptateur",
    membership_role: str = "adaptateur",
    plan: str = "pro",
):
    db = _db()
    try:
        studio_id = uuid.uuid4()
        user_id = uuid.uuid4()
        db.add(Studio(id=studio_id, name=studio_name, plan=plan))
        db.add(
            User(
                id=user_id,
                email=email,
                hashed_password=hash_password("Pass123!"),
                role=global_role,
                is_active=True,
            )
        )
        db.add(
            StudioMembership(
                id=uuid.uuid4(),
                studio_id=studio_id,
                user_id=user_id,
                role=membership_role,
            )
        )
        db.commit()
        token = create_access_token(
            {
                "sub": str(user_id),
                "email": email,
                "role": global_role,
                "tv": 0,
            }
        )
        return {
            "studio_id": studio_id,
            "user_id": user_id,
            "token": token,
            "headers": {"Authorization": f"Bearer {token}"},
        }
    finally:
        db.close()


def _add_user(
    studio_id,
    email: str,
    *,
    global_role: str = "adaptateur",
    membership_role: str = "adaptateur",
):
    """Ajoute un utilisateur à un studio EXISTANT (même tenant)."""
    db = _db()
    try:
        user_id = uuid.uuid4()
        db.add(
            User(
                id=user_id,
                email=email,
                hashed_password=hash_password("Pass123!"),
                role=global_role,
                is_active=True,
            )
        )
        db.add(
            StudioMembership(
                id=uuid.uuid4(),
                studio_id=studio_id,
                user_id=user_id,
                role=membership_role,
            )
        )
        db.commit()
        token = create_access_token(
            {
                "sub": str(user_id),
                "email": email,
                "role": global_role,
                "tv": 0,
            }
        )
        return {
            "studio_id": studio_id,
            "user_id": user_id,
            "token": token,
            "headers": {"Authorization": f"Bearer {token}"},
        }
    finally:
        db.close()


def _set_preferences(user_id, theme="dark", language="fr"):
    db = _db()
    try:
        db.add(
            UserPreferences(
                user_id=user_id, theme=theme, language=language, custom_shortcuts={}
            )
        )
        db.commit()
    finally:
        db.close()


# ============================================================
# Profil
# ============================================================
class TestProfile:
    def setup_method(self):
        _clean()
        self.u = _make_user("alice@studio.com", studio_name="Studio Alice")

    def test_get_me_full_profile(self):
        _set_preferences(self.u["user_id"])
        r = client.get("/api/v1/users/me", headers=self.u["headers"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["email"] == "alice@studio.com"
        assert data["is_active"] is True
        assert len(data["memberships"]) == 1
        assert data["memberships"][0]["studio_name"] == "Studio Alice"
        assert data["preferences"] is not None
        assert data["preferences"]["theme"] == "dark"

    def test_get_me_requires_auth(self):
        assert client.get("/api/v1/users/me").status_code == 401

    def test_patch_email(self):
        r = client.patch(
            "/api/v1/users/me",
            headers=self.u["headers"],
            json={"email": "alice2@studio.com"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["email"] == "alice2@studio.com"

    def test_patch_email_conflict(self):
        _make_user("bob@studio.com", studio_name="Studio Bob")
        r = client.patch(
            "/api/v1/users/me",
            headers=self.u["headers"],
            json={"email": "bob@studio.com"},
        )
        assert r.status_code == 409

    def test_patch_password_then_login(self):
        r = client.patch(
            "/api/v1/users/me",
            headers=self.u["headers"],
            json={"current_password": "Pass123!", "new_password": "Nouveau456!"},
        )
        assert r.status_code == 200, r.text
        # Login avec l'ancien mot de passe échoue
        old = client.post(
            "/auth/login", json={"email": "alice@studio.com", "password": "Pass123!"}
        )
        assert old.status_code == 401
        # Login avec le nouveau mot de passe fonctionne
        new = client.post(
            "/auth/login",
            json={"email": "alice@studio.com", "password": "Nouveau456!"},
        )
        assert new.status_code == 200

    def test_patch_password_wrong_current(self):
        r = client.patch(
            "/api/v1/users/me",
            headers=self.u["headers"],
            json={"current_password": "wrong", "new_password": "Nouveau456!"},
        )
        assert r.status_code == 403

    def test_patch_password_pwned_rejected(self):
        r = client.patch(
            "/api/v1/users/me",
            headers=self.u["headers"],
            json={"current_password": "Pass123!", "new_password": "password"},
        )
        assert r.status_code == 400


# ============================================================
# Désactivation
# ============================================================
class TestDeactivation:
    def setup_method(self):
        _clean()
        # Utilisateur non-admin (pas de MFA requise au login)
        self.u = _make_user("carol@studio.com", studio_name="Studio Carol")

    def test_self_deactivate_revokes_login(self):
        r = client.post(
            "/api/v1/users/me/deactivate", headers=self.u["headers"]
        )
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False
        # La connexion est désormais refusée (compte désactivé)
        login = client.post(
            "/auth/login",
            json={"email": "carol@studio.com", "password": "Pass123!"},
        )
        assert login.status_code == 403

    def test_admin_deactivate_then_reactivate(self):
        admin = _add_user(
            self.u["studio_id"],
            "admin@studio.com",
            global_role="admin",
            membership_role="admin",
        )
        # Désactivation par l'admin
        r = client.patch(
            f"/api/v1/users/{self.u['user_id']}/status",
            headers=admin["headers"],
            json={"is_active": False},
        )
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False
        # Réactivation
        r2 = client.patch(
            f"/api/v1/users/{self.u['user_id']}/status",
            headers=admin["headers"],
            json={"is_active": True},
        )
        assert r2.status_code == 200
        assert r2.json()["is_active"] is True


# ============================================================
# Permissions & opérations administratives
# ============================================================
class TestAdminAndPermissions:
    def setup_method(self):
        _clean()
        self.admin = _make_user(
            "admin@a.com",
            studio_name="Studio A",
            global_role="admin",
            membership_role="admin",
        )
        self.member = _add_user(self.admin["studio_id"], "member@a.com")

    def test_non_admin_cannot_list_users(self):
        r = client.get("/api/v1/users", headers=self.member["headers"])
        assert r.status_code == 403

    def test_non_admin_cannot_view_user(self):
        r = client.get(
            f"/api/v1/users/{self.member['user_id']}",
            headers=self.member["headers"],
        )
        assert r.status_code == 403

    def test_admin_lists_studio_users(self):
        r = client.get("/api/v1/users", headers=self.admin["headers"])
        assert r.status_code == 200, r.text
        emails = {u["email"] for u in r.json()}
        # admin + member sont dans Studio A
        assert "admin@a.com" in emails and "member@a.com" in emails

    def test_admin_views_user(self):
        r = client.get(
            f"/api/v1/users/{self.member['user_id']}",
            headers=self.admin["headers"],
        )
        assert r.status_code == 200, r.text
        assert r.json()["email"] == "member@a.com"

    def test_admin_deletes_user(self):
        r = client.delete(
            f"/api/v1/users/{self.member['user_id']}",
            headers=self.admin["headers"],
        )
        assert r.status_code == 204
        # L'utilisateur n'existe plus
        db = _db()
        try:
            assert (
                db.query(User).filter(User.id == self.member["user_id"]).first()
                is None
            )
        finally:
            db.close()


# ============================================================
# Refus inter-studios (anti-IDOR)
# ============================================================
class TestInterStudioRefusal:
    def setup_method(self):
        _clean()
        self.admin_a = _make_user(
            "admina@a.com",
            studio_name="Studio A",
            global_role="admin",
            membership_role="admin",
        )
        self.user_b = _make_user("userb@b.com", studio_name="Studio B")

    def test_admin_a_cannot_view_studio_b_user(self):
        r = client.get(
            f"/api/v1/users/{self.user_b['user_id']}",
            headers=self.admin_a["headers"],
        )
        assert r.status_code == 403

    def test_admin_a_cannot_deactivate_studio_b_user(self):
        r = client.patch(
            f"/api/v1/users/{self.user_b['user_id']}/status",
            headers=self.admin_a["headers"],
            json={"is_active": False},
        )
        assert r.status_code == 403
        # user_b reste actif
        db = _db()
        try:
            u = db.query(User).filter(User.id == self.user_b["user_id"]).first()
            assert u.is_active is True
        finally:
            db.close()

    def test_admin_a_cannot_delete_studio_b_user(self):
        r = client.delete(
            f"/api/v1/users/{self.user_b['user_id']}",
            headers=self.admin_a["headers"],
        )
        assert r.status_code == 403
        db = _db()
        try:
            assert (
                db.query(User).filter(User.id == self.user_b["user_id"]).first()
                is not None
            )
        finally:
            db.close()

    def test_admin_list_excludes_other_studio(self):
        r = client.get("/api/v1/users", headers=self.admin_a["headers"])
        emails = {u["email"] for u in r.json()}
        assert "userb@b.com" not in emails


# ============================================================
# Contrat OpenAPI
# ============================================================
def test_openapi_exposes_users_endpoints():
    """Le contrat OpenAPI expose les endpoints Users prévus (§10.2)."""
    schema = app.openapi()
    expected = {
        ("/api/v1/users/me", "get"),
        ("/api/v1/users/me", "patch"),
        ("/api/v1/users/me", "delete"),
        ("/api/v1/users/me/deactivate", "post"),
        ("/api/v1/users/me/preferences", "get"),
        ("/api/v1/users/me/preferences", "put"),
        ("/api/v1/users", "get"),
        ("/api/v1/users/{user_id}", "get"),
        ("/api/v1/users/{user_id}", "delete"),
        ("/api/v1/users/{user_id}/status", "patch"),
        ("/api/v1/studios/{studio_id}/users", "get"),
        ("/api/v1/studios/{studio_id}/users/invite", "post"),
    }
    actual = set()
    for path, methods in schema["paths"].items():
        for method in methods:
            actual.add((path, method))
    missing = expected - actual
    assert not missing, f"Endpoints Users manquants du contrat OpenAPI: {missing}"
