"""
Tests CRUD Project + activité (CDC §10.2 & §16.1) — G-013.

Couvre : CRUD, pagination, cycle de vie, activité, RBAC et **anti-IDOR**
inter-studios.

Harnais auto-contenu (SQLite synchrone + surcharge de `get_db`).
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
from app.models import (
    Base,
    Export,
    MediaAsset,
    Project,
    RythmoBand,
    RythmoVersion,
    Studio,
    StudioMembership,
    Task,
    User,
)


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
        for m in (
            RythmoVersion,
            Export,
            Task,
            MediaAsset,
            RythmoBand,
            Project,
            StudioMembership,
            User,
            Studio,
        ):
            db.query(m).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _make_tenant(name: str, *, global_role="adaptateur", member_role="adaptateur"):
    db = _db()
    try:
        studio_id = uuid.uuid4()
        user_id = uuid.uuid4()
        db.add(Studio(id=studio_id, name=name, plan="pro"))
        db.add(
            User(
                id=user_id,
                email=f"user_{name}@x.com",
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
                role=member_role,
            )
        )
        db.commit()
        token = create_access_token(
            {"sub": str(user_id), "email": f"user_{name}@x.com", "role": global_role, "tv": 0}
        )
        return {
            "studio_id": studio_id,
            "user_id": user_id,
            "headers": {"Authorization": f"Bearer {token}"},
        }
    finally:
        db.close()


def _add_admin(studio_id, email="admin@x.com"):
    db = _db()
    try:
        user_id = uuid.uuid4()
        db.add(
            User(
                id=user_id,
                email=email,
                hashed_password=hash_password("Pass123!"),
                role="admin",
                is_active=True,
            )
        )
        db.add(
            StudioMembership(
                id=uuid.uuid4(), studio_id=studio_id, user_id=user_id, role="admin"
            )
        )
        db.commit()
        token = create_access_token(
            {"sub": str(user_id), "email": email, "role": "admin", "tv": 0}
        )
        return {"user_id": user_id, "headers": {"Authorization": f"Bearer {token}"}}
    finally:
        db.close()


def _create_project_via_api(headers, studio_id, title="Projet"):
    r = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"title": title, "studio_id": str(studio_id)},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_project_in_db(studio_id, title, status="Cree"):
    db = _db()
    try:
        p = Project(id=uuid.uuid4(), studio_id=studio_id, title=title, status=status)
        db.add(p)
        db.commit()
        db.refresh(p)
        return p.id
    finally:
        db.close()


# ============================================================
# CRUD
# ============================================================
class TestCRUD:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("A")

    def test_create_project(self):
        data = _create_project_via_api(self.a["headers"], self.a["studio_id"], "Mon projet")
        assert data["title"] == "Mon projet"
        assert data["status"] == "Cree"
        assert data["studio_id"] == str(self.a["studio_id"])

    def test_list_projects(self):
        for i in range(3):
            _create_project_via_api(self.a["headers"], self.a["studio_id"], f"P{i}")
        r = client.get("/api/v1/projects", headers=self.a["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3

    def test_pagination(self):
        for i in range(5):
            _create_project_via_api(self.a["headers"], self.a["studio_id"], f"P{i}")
        r = client.get(
            "/api/v1/projects?page=1&page_size=2", headers=self.a["headers"]
        )
        body = r.json()
        assert body["total"] == 5
        assert body["page"] == 1 and body["page_size"] == 2
        assert len(body["items"]) == 2
        r3 = client.get(
            "/api/v1/projects?page=3&page_size=2", headers=self.a["headers"]
        )
        assert len(r3.json()["items"]) == 1  # 5 = 2+2+1

    def test_get_project(self):
        pid = _create_project_via_api(self.a["headers"], self.a["studio_id"], "X")["id"]
        r = client.get(f"/api/v1/projects/{pid}", headers=self.a["headers"])
        assert r.status_code == 200
        assert r.json()["title"] == "X"

    def test_patch_project(self):
        pid = _create_project_via_api(self.a["headers"], self.a["studio_id"], "X")["id"]
        r = client.patch(
            f"/api/v1/projects/{pid}",
            headers=self.a["headers"],
            json={"title": "Renommé", "source_lang": "en"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "Renommé"
        assert r.json()["source_lang"] == "en"


# ============================================================
# Cycle de vie
# ============================================================
class TestLifecycle:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("A")

    def test_status_transition_reflected_in_project(self):
        pid = _create_project_via_api(self.a["headers"], self.a["studio_id"])["id"]
        # Transition Cree -> En_traitement (autorée par le graphe §16.1)
        r = client.patch(
            f"/api/v1/projects/{pid}/status",
            json={"status": "En_traitement"},
        )
        assert r.status_code == 200, r.text
        # Le GET du projet reflète le nouveau statut
        g = client.get(f"/api/v1/projects/{pid}", headers=self.a["headers"])
        assert g.json()["status"] == "En_traitement"

    def test_get_project_status(self):
        pid = _create_project_via_api(self.a["headers"], self.a["studio_id"])["id"]
        r = client.get(f"/api/v1/projects/{pid}/status")
        assert r.status_code == 200
        assert r.json()["status"] == "Cree"


# ============================================================
# Suppression contrôlée
# ============================================================
class TestDelete:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("A")
        self.admin = _add_admin(self.a["studio_id"])
        self.pid = _create_project_via_api(self.a["headers"], self.a["studio_id"])["id"]

    def test_non_admin_cannot_delete(self):
        r = client.delete(f"/api/v1/projects/{self.pid}", headers=self.a["headers"])
        assert r.status_code == 403

    def test_admin_deletes(self):
        r = client.delete(f"/api/v1/projects/{self.pid}", headers=self.admin["headers"])
        assert r.status_code == 204
        # Vérifie la disparition
        db = _db()
        try:
            assert (
                db.query(Project)
                .filter(Project.id == uuid.UUID(self.pid))
                .first()
                is None
            )
        finally:
            db.close()

    def test_delete_cascades_media_and_band(self):
        db = _db()
        try:
            db.add(MediaAsset(id=uuid.uuid4(), project_id=uuid.UUID(self.pid), storage_path="x", status="confirmed"))
            db.add(RythmoBand(id=uuid.uuid4(), project_id=uuid.UUID(self.pid), version_number=1, status="draft", is_master=True))
            db.commit()
        finally:
            db.close()
        r = client.delete(f"/api/v1/projects/{self.pid}", headers=self.admin["headers"])
        assert r.status_code == 204
        db = _db()
        try:
            assert db.query(MediaAsset).filter(MediaAsset.project_id == uuid.UUID(self.pid)).count() == 0
            assert db.query(RythmoBand).filter(RythmoBand.project_id == uuid.UUID(self.pid)).count() == 0
        finally:
            db.close()


# ============================================================
# Anti-IDOR inter-studios
# ============================================================
class TestAntiIDOR:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("A")
        self.b = _make_tenant("B")
        self.proj_a = _create_project_via_api(self.a["headers"], self.a["studio_id"], "Secret A")

    def test_list_excludes_other_studio(self):
        r = client.get("/api/v1/projects", headers=self.b["headers"])
        titles = {p["title"] for p in r.json()["items"]}
        assert "Secret A" not in titles

    def test_cannot_get_other_studio_project(self):
        r = client.get(
            f"/api/v1/projects/{self.proj_a['id']}", headers=self.b["headers"]
        )
        assert r.status_code == 404

    def test_cannot_patch_other_studio_project(self):
        r = client.patch(
            f"/api/v1/projects/{self.proj_a['id']}",
            headers=self.b["headers"],
            json={"title": "hack"},
        )
        assert r.status_code == 404

    def test_cannot_delete_other_studio_project(self):
        admin_b = _add_admin(self.b["studio_id"], email="adminb@x.com")
        r = client.delete(
            f"/api/v1/projects/{self.proj_a['id']}", headers=admin_b["headers"]
        )
        assert r.status_code == 404
        # Le projet existe toujours
        assert client.get(
            f"/api/v1/projects/{self.proj_a['id']}", headers=self.a["headers"]
        ).status_code == 200

    def test_cannot_view_other_studio_activity(self):
        r = client.get(
            f"/api/v1/projects/{self.proj_a['id']}/activity", headers=self.b["headers"]
        )
        assert r.status_code == 404

    def test_cannot_list_other_studio_explicitly(self):
        r = client.get(
            f"/api/v1/projects?studio_id={self.a['studio_id']}",
            headers=self.b["headers"],
        )
        assert r.status_code == 403


# ============================================================
# RBAC
# ============================================================
class TestRBAC:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("A")

    def test_unauthenticated_list(self):
        assert client.get("/api/v1/projects").status_code == 401

    def test_unauthenticated_get(self):
        pid = _create_project_via_api(self.a["headers"], self.a["studio_id"])["id"]
        assert client.get(f"/api/v1/projects/{pid}").status_code == 401

    def test_create_in_non_member_studio(self):
        other = _make_tenant("Other")
        r = client.post(
            "/api/v1/projects",
            headers=self.a["headers"],
            json={"title": "x", "studio_id": str(other["studio_id"])},
        )
        assert r.status_code == 403


# ============================================================
# Activité
# ============================================================
class TestActivity:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("A")
        self.pid = _create_project_via_api(self.a["headers"], self.a["studio_id"])["id"]

    def test_activity_returns_events(self):
        db = _db()
        try:
            db.add(MediaAsset(id=uuid.uuid4(), project_id=uuid.UUID(self.pid), storage_path="m.mp4", status="confirmed"))
            db.add(RythmoVersion(id=uuid.uuid4(), project_id=uuid.UUID(self.pid), version_number=1))
            db.add(Task(studio_id=self.a["studio_id"], project_id=uuid.UUID(self.pid), title="Relire", status="à_faire", created_by=self.a["user_id"]))
            db.commit()
        finally:
            db.close()
        r = client.get(
            f"/api/v1/projects/{self.pid}/activity", headers=self.a["headers"]
        )
        assert r.status_code == 200, r.text
        types = {e["type"] for e in r.json()["events"]}
        assert {"media_uploaded", "version_saved", "task"}.issubset(types)

    def test_activity_sorted_desc(self):
        db = _db()
        try:
            db.add(MediaAsset(id=uuid.uuid4(), project_id=uuid.UUID(self.pid), storage_path="a", status="confirmed"))
            db.add(Export(id=uuid.uuid4(), project_id=uuid.UUID(self.pid), format="pdf", status="ready"))
            db.commit()
        finally:
            db.close()
        r = client.get(
            f"/api/v1/projects/{self.pid}/activity", headers=self.a["headers"]
        )
        timestamps = [e["timestamp"] for e in r.json()["events"]]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_empty_activity(self):
        r = client.get(
            f"/api/v1/projects/{self.pid}/activity", headers=self.a["headers"]
        )
        assert r.status_code == 200
        assert r.json()["events"] == []
