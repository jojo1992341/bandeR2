"""
Tests G-008 — Modélisation préférences, organisation et activité (§16.1–§16.3 CDC).

Couvre :
- §16.2 Préférences utilisateur (thème, langue, raccourcis) — CRUD `/me`.
- §16.1 Organisation des projets : dossiers & tags studio-scopés, affectation à un projet.
- §16.3 Équipes / sous-groupes (plan Enterprise) + membres.
- §16.2 Tâches assignées + Vue « Mon activité ».
- **Anti-IDOR (§15.7)** : aucun tenant ne lit ni ne modifie l'organisation d'un autre.

Le harnais de test est volontairement auto-contenu (moteur SQLite synchrone en
mémoire + surcharge de la dépendance `get_db`) afin d'être reproductible quel que
soit l'environnement d'exécution.
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
    Project,
    ProjectFolder,
    ProjectTag,
    Studio,
    StudioMembership,
    Task,
    Team,
    TeamMembership,
    User,
    UserPreferences,
)

# ------------------------------------------------------------------
# Harnais : moteur SQLite synchrone partagé + surcharge de get_db
# ------------------------------------------------------------------
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
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


# Le harnais global répare désormais `get_db` (synchrone), mais d'autres modules
# de test appellent `app.dependency_overrides.clear()` ; on pose donc notre
# surcharge AVANT chaque test (et on la restaure après) pour garantir que setup
# (notre engine) et routes partagent bien la même base isolée.
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


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _db():
    return _TestingSessionLocal()


def _clean():
    db = _db()
    try:
        for model in (
            Task,
            TeamMembership,
            Team,
            ProjectTag,
            ProjectFolder,
            Project,
            UserPreferences,
            StudioMembership,
            User,
            Studio,
        ):
            db.query(model).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _make_tenant(name: str, plan: str = "enterprise"):
    """Crée un studio + un utilisateur membre + un token, et les retourne."""
    db = _db()
    try:
        studio_id = uuid.uuid4()
        user_id = uuid.uuid4()
        db.add(Studio(id=studio_id, name=name, plan=plan))
        db.add(
            User(
                id=user_id,
                email=f"user_{name.replace(' ', '_')}@example.com",
                hashed_password=hash_password("Pass123!"),
                role="adaptateur",
                is_active=True,
            )
        )
        db.add(
            StudioMembership(
                id=uuid.uuid4(),
                studio_id=studio_id,
                user_id=user_id,
                role="adaptateur",
            )
        )
        db.commit()
        token = create_access_token(
            {
                "sub": str(user_id),
                "email": f"user_{name}@example.com",
                "role": "adaptateur",
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


def _make_project(studio_id, title="Projet test"):
    db = _db()
    try:
        p = Project(
            id=uuid.uuid4(),
            studio_id=studio_id,
            title=title,
            status="Cree",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return p.id
    finally:
        db.close()


# ============================================================
# §16.2 — Préférences utilisateur
# ============================================================
class TestPreferences:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("StudioA")
        self.b = _make_tenant("StudioB")

    def test_get_creates_defaults(self):
        r = client.get("/api/v1/users/me/preferences", headers=self.a["headers"])
        assert r.status_code == 200
        data = r.json()
        assert data["theme"] == "system"
        assert data["language"] == "fr"
        assert data["custom_shortcuts"] == {}
        assert data["user_id"] == str(self.a["user_id"])

    def test_update_preferences(self):
        r = client.put(
            "/api/v1/users/me/preferences",
            headers=self.a["headers"],
            json={
                "theme": "dark",
                "language": "en",
                "custom_shortcuts": {"save": "Ctrl+S", "play": "Space"},
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["theme"] == "dark"
        assert data["language"] == "en"
        assert data["custom_shortcuts"]["save"] == "Ctrl+S"

        # Persistance
        r2 = client.get("/api/v1/users/me/preferences", headers=self.a["headers"])
        assert r2.json()["theme"] == "dark"

    def test_invalid_theme_rejected(self):
        r = client.put(
            "/api/v1/users/me/preferences",
            headers=self.a["headers"],
            json={"theme": "neon"},
        )
        assert r.status_code == 400

    def test_preferences_isolation_between_users(self):
        """Chaque utilisateur a ses propres préférences (anti-IDOR utilisateur)."""
        client.put(
            "/api/v1/users/me/preferences",
            headers=self.a["headers"],
            json={"theme": "dark"},
        )
        # L'utilisateur B voit ses propres valeurs par défaut, pas celles de A
        r = client.get("/api/v1/users/me/preferences", headers=self.b["headers"])
        assert r.status_code == 200
        assert r.json()["theme"] == "system"

    def test_preferences_require_auth(self):
        r = client.get("/api/v1/users/me/preferences")
        assert r.status_code == 401


# ============================================================
# §16.1 — Dossiers & Tags
# ============================================================
class TestFoldersAndTags:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("StudioA")
        self.b = _make_tenant("StudioB")

    # -- CRUD nominal --
    def test_folder_crud(self):
        sid = self.a["studio_id"]
        h = self.a["headers"]
        r = client.post(f"/api/v1/studios/{sid}/folders", headers=h, json={"name": "Pôle jeunesse"})
        assert r.status_code == 201, r.text
        folder = r.json()
        assert folder["name"] == "Pôle jeunesse"
        assert folder["studio_id"] == str(sid)

        # Nested folder
        r2 = client.post(
            f"/api/v1/studios/{sid}/folders",
            headers=h,
            json={"name": "Saison 1", "parent_folder_id": folder["id"]},
        )
        assert r2.status_code == 201

        # List
        r3 = client.get(f"/api/v1/studios/{sid}/folders", headers=h)
        assert r3.status_code == 200
        assert len(r3.json()) == 2

        # Update
        r4 = client.put(
            f"/api/v1/studios/{sid}/folders/{folder['id']}", headers=h, json={"name": "Pôle films"}
        )
        assert r4.status_code == 200
        assert r4.json()["name"] == "Pôle films"

        # Delete
        r5 = client.delete(f"/api/v1/studios/{sid}/folders/{folder['id']}", headers=h)
        assert r5.status_code == 204

    def test_tag_crud(self):
        sid = self.a["studio_id"]
        h = self.a["headers"]
        r = client.post(f"/api/v1/studios/{sid}/tags", headers=h, json={"name": "diffuseur-ARTE", "color": "#ff0000"})
        assert r.status_code == 201, r.text
        tag = r.json()
        assert tag["color"] == "#ff0000"

        r2 = client.get(f"/api/v1/studios/{sid}/tags", headers=h)
        assert len(r2.json()) == 1

        r3 = client.delete(f"/api/v1/studios/{sid}/tags/{tag['id']}", headers=h)
        assert r3.status_code == 204

    # -- Anti-IDOR --
    def test_idor_folder_in_other_tenant_invisible(self):
        """Un membre du studio B ne peut pas lire le dossier du studio A par son ID."""
        sid_a = self.a["studio_id"]
        h_a = self.a["headers"]
        h_b = self.b["headers"]

        folder = client.post(
            f"/api/v1/studios/{sid_a}/folders", headers=h_a, json={"name": "Secret A"}
        ).json()

        # B tente de lister les dossiers de A -> 403 (pas membre)
        assert client.get(f"/api/v1/studios/{sid_a}/folders", headers=h_b).status_code == 403

        # B tente de lire le dossier de A via le bon chemin studio A -> 403
        assert (
            client.get(f"/api/v1/studios/{sid_a}/folders/{folder['id']}", headers=h_b).status_code
            == 403
        )

        # B tente de modifier / supprimer le dossier de A -> 403
        assert (
            client.put(
                f"/api/v1/studios/{sid_a}/folders/{folder['id']}",
                headers=h_b,
                json={"name": "hack"},
            ).status_code
            == 403
        )
        assert (
            client.delete(f"/api/v1/studios/{sid_a}/folders/{folder['id']}", headers=h_b).status_code
            == 403
        )
        # Le dossier existe toujours
        assert (
            client.get(f"/api/v1/studios/{sid_a}/folders/{folder['id']}", headers=h_a).status_code
            == 200
        )

    def test_idor_tag_in_other_tenant_invisible(self):
        sid_a = self.a["studio_id"]
        h_a = self.a["headers"]
        h_b = self.b["headers"]
        tag = client.post(
            f"/api/v1/studios/{sid_a}/tags", headers=h_a, json={"name": "client-X"}
        ).json()
        assert client.get(f"/api/v1/studios/{sid_a}/tags/{tag['id']}", headers=h_b).status_code == 403
        assert (
            client.delete(f"/api/v1/studios/{sid_a}/tags/{tag['id']}", headers=h_b).status_code
            == 403
        )

    def test_create_in_non_member_studio_forbidden(self):
        """Créer un dossier/tag dans un studio dont on n'est pas membre -> 403."""
        sid_a = self.a["studio_id"]
        h_b = self.b["headers"]
        assert (
            client.post(f"/api/v1/studios/{sid_a}/folders", headers=h_b, json={"name": "x"}).status_code
            == 403
        )
        assert (
            client.post(f"/api/v1/studios/{sid_a}/tags", headers=h_b, json={"name": "x"}).status_code
            == 403
        )

    def test_folder_parent_in_other_tenant_rejected(self):
        """Le dossier parent doit appartenir au même studio."""
        sid_a = self.a["studio_id"]
        sid_b = self.b["studio_id"]
        h_a = self.a["headers"]
        folder_a = client.post(
            f"/api/v1/studios/{sid_a}/folders", headers=h_a, json={"name": "A"}
        ).json()
        # A tente de créer un sous-dossier de A dans le studio B (path B) -> 403 (non membre)
        r = client.post(
            f"/api/v1/studios/{sid_b}/folders",
            headers=h_a,
            json={"name": "sous", "parent_folder_id": folder_a["id"]},
        )
        assert r.status_code == 403


# ============================================================
# §16.1 — Affectation dossier/tags à un projet
# ============================================================
class TestProjectOrganize:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("StudioA")
        self.b = _make_tenant("StudioB")
        self.proj_a = _make_project(self.a["studio_id"], "Projet A")
        self.proj_b = _make_project(self.b["studio_id"], "Projet B")

    def test_organize_own_project(self):
        sid = self.a["studio_id"]
        h = self.a["headers"]
        folder = client.post(f"/api/v1/studios/{sid}/folders", headers=h, json={"name": "F"}).json()
        tag = client.post(f"/api/v1/studios/{sid}/tags", headers=h, json={"name": "T"}).json()
        r = client.post(
            f"/api/v1/projects/{self.proj_a}/organize",
            headers=h,
            json={"folder_id": folder["id"], "tag_ids": [tag["id"]]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["folder_id"] == folder["id"]
        assert r.json()["tag_ids"] == [tag["id"]]

    def test_idor_organize_other_tenant_project(self):
        """B ne peut pas réorganiser un projet du studio A."""
        sid = self.a["studio_id"]
        h_a = self.a["headers"]
        h_b = self.b["headers"]
        folder = client.post(f"/api/v1/studios/{sid}/folders", headers=h_a, json={"name": "F"}).json()
        # B tente d'organiser le projet A -> 404 (projet d'un autre tenant invisible)
        r = client.post(
            f"/api/v1/projects/{self.proj_a}/organize",
            headers=h_b,
            json={"folder_id": folder["id"]},
        )
        assert r.status_code == 404

    def test_idor_organize_with_other_tenant_folder(self):
        """A ne peut pas attacher à son projet un dossier appartenant à B."""
        sid_a = self.a["studio_id"]
        sid_b = self.b["studio_id"]
        h_a = self.a["headers"]
        h_b = self.b["headers"]
        folder_b = client.post(f"/api/v1/studios/{sid_b}/folders", headers=h_b, json={"name": "FB"}).json()
        r = client.post(
            f"/api/v1/projects/{self.proj_a}/organize",
            headers=h_a,
            json={"folder_id": folder_b["id"]},
        )
        assert r.status_code == 404  # dossier d'un autre tenant -> invisible


# ============================================================
# §16.3 — Équipes (Enterprise)
# ============================================================
class TestTeams:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("StudioA", plan="enterprise")
        self.b = _make_tenant("StudioB", plan="enterprise")

    def test_team_crud_and_members(self):
        sid = self.a["studio_id"]
        h = self.a["headers"]
        team = client.post(
            f"/api/v1/studios/{sid}/teams", headers=h, json={"name": "Pôle films"}
        ).json()
        assert team["name"] == "Pôle films"

        # Ajout d'un membre (l'utilisateur A lui-même est membre du studio)
        m = client.post(
            f"/api/v1/studios/{sid}/teams/{team['id']}/members",
            headers=h,
            json={"user_id": str(self.a["user_id"]), "role": "lead"},
        )
        assert m.status_code == 201, m.text
        assert m.json()["role"] == "lead"

        # Liste des membres
        members = client.get(f"/api/v1/studios/{sid}/teams/{team['id']}/members", headers=h).json()
        assert len(members) == 1

        # Suppression du membre
        assert (
            client.delete(
                f"/api/v1/studios/{sid}/teams/{team['id']}/members/{self.a['user_id']}", headers=h
            ).status_code
            == 204
        )

        # Suppression de l'équipe
        assert client.delete(f"/api/v1/studios/{sid}/teams/{team['id']}", headers=h).status_code == 204

    def test_teams_enterprise_only(self):
        """Les équipes sont réservées au plan Enterprise."""
        c = _make_tenant("StudioC", plan="pro")
        r = client.post(
            f"/api/v1/studios/{c['studio_id']}/teams", headers=c["headers"], json={"name": "X"}
        )
        assert r.status_code == 403
        assert "Enterprise" in r.json()["detail"]

    def test_idor_team_in_other_tenant(self):
        sid_a = self.a["studio_id"]
        h_a = self.a["headers"]
        h_b = self.b["headers"]
        team = client.post(
            f"/api/v1/studios/{sid_a}/teams", headers=h_a, json={"name": "Equipe A"}
        ).json()

        # B ne voit pas l'équipe de A (path studio A -> 403)
        assert (
            client.get(f"/api/v1/studios/{sid_a}/teams/{team['id']}", headers=h_b).status_code
            == 403
        )
        # B ne peut ni modifier ni supprimer
        assert (
            client.put(
                f"/api/v1/studios/{sid_a}/teams/{team['id']}", headers=h_b, json={"name": "hack"}
            ).status_code
            == 403
        )
        assert (
            client.delete(f"/api/v1/studios/{sid_a}/teams/{team['id']}", headers=h_b).status_code
            == 403
        )
        # B ne peut pas lister les équipes de A
        assert client.get(f"/api/v1/studios/{sid_a}/teams", headers=h_b).status_code == 403
        # L'équipe de A est intacte
        assert (
            client.get(f"/api/v1/studios/{sid_a}/teams/{team['id']}", headers=h_a).status_code == 200
        )

    def test_idor_add_member_from_other_tenant(self):
        """On ne peut pas ajouter à une équipe un utilisateur qui n'est pas membre du studio."""
        sid = self.a["studio_id"]
        h = self.a["headers"]
        team = client.post(
            f"/api/v1/studios/{sid}/teams", headers=h, json={"name": "Equipe A"}
        ).json()
        # user_id de B n'appartient pas au studio A
        r = client.post(
            f"/api/v1/studios/{sid}/teams/{team['id']}/members",
            headers=h,
            json={"user_id": str(self.b["user_id"])},
        )
        assert r.status_code == 404


# ============================================================
# §16.2 — Tâches & Vue « Mon activité »
# ============================================================
class TestTasksAndActivity:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("StudioA")
        self.b = _make_tenant("StudioB")

    def test_task_crud(self):
        sid = self.a["studio_id"]
        h = self.a["headers"]
        proj = _make_project(sid)
        r = client.post(
            f"/api/v1/studios/{sid}/tasks",
            headers=h,
            json={
                "title": "Relire répliques",
                "project_id": str(proj),
                "assignee_id": str(self.a["user_id"]),
            },
        )
        assert r.status_code == 201, r.text
        task = r.json()
        assert task["status"] == "à_faire"
        assert task["assignee_id"] == str(self.a["user_id"])
        assert task["created_by"] == str(self.a["user_id"])

        # Update
        r2 = client.put(
            f"/api/v1/studios/{sid}/tasks/{task['id']}", headers=h, json={"status": "terminée"}
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "terminée"

        # List
        assert len(client.get(f"/api/v1/studios/{sid}/tasks", headers=h).json()) == 1

        # Delete
        assert (
            client.delete(f"/api/v1/studios/{sid}/tasks/{task['id']}", headers=h).status_code == 204
        )

    def test_activity_aggregates_projects_and_tasks(self):
        sid = self.a["studio_id"]
        h = self.a["headers"]
        _make_project(sid, "Récent A")
        client.post(
            f"/api/v1/studios/{sid}/tasks",
            headers=h,
            json={"title": "Ma tâche", "assignee_id": str(self.a["user_id"])},
        )
        r = client.get("/api/v1/users/me/activity", headers=h)
        assert r.status_code == 200
        data = r.json()
        assert len(data["recent_projects"]) == 1
        assert data["recent_projects"][0]["title"] == "Récent A"
        assert len(data["assigned_tasks"]) == 1
        assert data["assigned_tasks"][0]["title"] == "Ma tâche"

    def test_idor_task_in_other_tenant(self):
        sid_a = self.a["studio_id"]
        h_a = self.a["headers"]
        h_b = self.b["headers"]
        task = client.post(
            f"/api/v1/studios/{sid_a}/tasks",
            headers=h_a,
            json={"title": "Tâche secrète A", "assignee_id": str(self.a["user_id"])},
        ).json()

        # B ne peut pas lire la tâche de A (path studio A -> 403)
        assert (
            client.get(f"/api/v1/studios/{sid_a}/tasks/{task['id']}", headers=h_b).status_code
            == 403
        )
        # B ne peut pas lister les tâches de A
        assert client.get(f"/api/v1/studios/{sid_a}/tasks", headers=h_b).status_code == 403
        # B ne peut ni modifier ni supprimer
        assert (
            client.put(
                f"/api/v1/studios/{sid_a}/tasks/{task['id']}", headers=h_b, json={"status": "terminée"}
            ).status_code
            == 403
        )
        assert (
            client.delete(f"/api/v1/studios/{sid_a}/tasks/{task['id']}", headers=h_b).status_code
            == 403
        )
        # La tâche de A est intacte
        assert (
            client.get(f"/api/v1/studios/{sid_a}/tasks/{task['id']}", headers=h_a).status_code
            == 200
        )

    def test_idor_assign_to_user_in_other_tenant(self):
        """On ne peut pas assigner une tâche à un utilisateur d'un autre studio."""
        sid = self.a["studio_id"]
        h = self.a["headers"]
        r = client.post(
            f"/api/v1/studios/{sid}/tasks",
            headers=h,
            json={"title": "Tâche", "assignee_id": str(self.b["user_id"])},
        )
        assert r.status_code == 404  # assignataire d'un autre tenant -> invisible

    def test_activity_does_not_leak_other_tenant(self):
        """L'activité de B ne contient ni les projets ni les tâches de A."""
        sid_a = self.a["studio_id"]
        h_a = self.a["headers"]
        h_b = self.b["headers"]
        _make_project(sid_a, "Projet secret A")
        client.post(
            f"/api/v1/studios/{sid_a}/tasks",
            headers=h_a,
            json={"title": "Tâche A (assignée à user A)", "assignee_id": str(self.a["user_id"])},
        )
        r = client.get("/api/v1/users/me/activity", headers=h_b)
        assert r.status_code == 200
        data = r.json()
        assert data["recent_projects"] == []
        assert data["assigned_tasks"] == []
