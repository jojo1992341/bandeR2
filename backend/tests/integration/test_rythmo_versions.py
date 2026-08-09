import uuid
import pytest
from app.models import Studio, Project, MediaAsset, Replica, RythmoVersion
# Réutiliser le même engine SQLite in-memory que les autres tests d'intégration
from .test_replica_split_merge import TestingSessionLocal, client, _clean_db, engine, Base

from app.core.auth_handler import create_access_token
from app.core.password import hash_password as _hash_pw

_auth_user_id = None
def _auth_headers():
    """Crée (une fois) un utilisateur authentifié pour les tests."""
    global _auth_user_id
    db = TestingSessionLocal()
    try:
        from app.models import User, StudioMembership
        studio = db.query(Studio).first()
        if not studio:
            return {}
        if _auth_user_id is None:
            u = User(id=uuid.uuid4(), email="authtest@rythmo.local",
                     hashed_password=_hash_pw("x"), role="adaptateur", is_active=True)
            db.add(u); db.flush()
            db.add(StudioMembership(id=uuid.uuid4(), studio_id=studio.id, user_id=u.id, role="adaptateur"))
            db.commit()
            _auth_user_id = u.id
        token = create_access_token({"sub": str(_auth_user_id), "email": "authtest@rythmo.local", "role": "adaptateur", "tv": 0})
        return {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _setup_project_with_replicas():
    db = TestingSessionLocal()
    try:
        _clean_db(db)
        studio = Studio(id=uuid.uuid4(), name="Studio Versions", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Projet Versions", source_lang="fr", target_lang="fr", status="draft")
        db.add(project); db.commit(); db.refresh(project)
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="test_versions.mp4", status="confirmed")
        db.add(media); db.commit(); db.refresh(media)
        # Créer 2 répliques initiales
        r1 = Replica(id=uuid.uuid4(), media_id=media.id, text="Bonjour le monde", start_ms=0, end_ms=2000, order_index=0, typo_codes={}, confidence_score=0.9)
        r2 = Replica(id=uuid.uuid4(), media_id=media.id, text="Au revoir", start_ms=2000, end_ms=4000, order_index=1, typo_codes={})
        db.add_all([r1, r2]); db.commit()
        db.refresh(r1); db.refresh(r2)
        return studio, project, media, [r1, r2]
    finally:
        db.close()

def test_create_two_versions_and_list():
    studio, project, media, replicas = _setup_project_with_replicas()
    try:
        # Version 1
        resp1 = client.post(f"/api/v1/projects/{project.id}/rythmo/versions", json={"comment": "Version initiale"}, headers=_auth_headers())
        assert resp1.status_code == 200, resp1.text
        v1 = resp1.json()
        assert v1["version_number"] == 1
        assert v1["comment"] == "Version initiale"
        assert v1["replica_count"] == 2

        # Modifier une réplique (simuler édition)
        r1_id = replicas[0].id
        resp_patch = client.patch(f"/api/v1/replicas/{r1_id}", json={"text": "Bonjour modifié"}, headers=_auth_headers())
        assert resp_patch.status_code == 200

        # Version 2 après modification
        resp2 = client.post(f"/api/v1/projects/{project.id}/rythmo/versions", json={"comment": "Après modif texte"}, headers=_auth_headers())
        assert resp2.status_code == 200
        v2 = resp2.json()
        assert v2["version_number"] == 2
        assert v2["replica_count"] == 2

        # Lister les versions
        resp_list = client.get(f"/api/v1/projects/{project.id}/rythmo/versions", headers=_auth_headers())
        assert resp_list.status_code == 200
        data = resp_list.json()
        assert data["count"] == 2
        assert len(data["versions"]) == 2
        assert data["versions"][0]["version_number"] == 1
        assert data["versions"][1]["version_number"] == 2

        # Nettoyage
        db = TestingSessionLocal(); _clean_db(db); db.close()
    finally:
        pass

def test_consult_version_and_restore():
    studio, project, media, replicas = _setup_project_with_replicas()
    try:
        # Version 1 avec texte original
        resp1 = client.post(f"/api/v1/projects/{project.id}/rythmo/versions", json={"comment": "v1"}, headers=_auth_headers())
        v1_id = resp1.json()["id"]
        v1_number = resp1.json()["version_number"]

        # Modifier
        r1_id = replicas[0].id
        client.patch(f"/api/v1/replicas/{r1_id}", json={"text": "Texte modifié v2", "typo_codes": {"italique": True}}, headers=_auth_headers())

        # Version 2
        resp2 = client.post(f"/api/v1/projects/{project.id}/rythmo/versions", json={"comment": "v2"}, headers=_auth_headers())
        v2_id = resp2.json()["id"]

        # Consulter version 1
        resp_get_v1 = client.get(f"/api/v1/projects/{project.id}/rythmo/versions/{v1_id}", headers=_auth_headers())
        assert resp_get_v1.status_code == 200
        v1_data = resp_get_v1.json()
        assert v1_data["version_number"] == 1
        snap_v1 = v1_data["snapshot"]
        assert any(r["text"] == "Bonjour le monde" for r in snap_v1)
        assert not any(r.get("typo_codes", {}).get("italique") for r in snap_v1)

        # Consulter version 2
        resp_get_v2 = client.get(f"/api/v1/projects/{project.id}/rythmo/versions/{v2_id}", headers=_auth_headers())
        assert resp_get_v2.status_code == 200
        snap_v2 = resp_get_v2.json()["snapshot"]
        assert any(r["text"] == "Texte modifié v2" for r in snap_v2)

        # Restaurer version 1
        resp_restore = client.post(f"/api/v1/projects/{project.id}/rythmo/versions/{v1_id}/restore", headers=_auth_headers())
        assert resp_restore.status_code == 200
        assert resp_restore.json()["restored_version_number"] == 1
        assert resp_restore.json()["status"] == "restored"

        # Vérifier que les répliques actuelles sont revenues à v1
        resp_replicas = client.get(f"/api/v1/projects/{project.id}/replicas", headers=_auth_headers())
        if resp_replicas.status_code == 200:
            current = resp_replicas.json()
            assert any(r["text"] == "Bonjour le monde" for r in current)
            assert not any(r.get("typo_codes", {}).get("italique") for r in current)
        else:
            db = TestingSessionLocal()
            media_ids = [m.id for m in db.query(MediaAsset).filter(MediaAsset.project_id == project.id).all()]
            current_reps = db.query(Replica).filter(Replica.media_id.in_(media_ids)).all()
            assert any(r.text == "Bonjour le monde" for r in current_reps)
            db.close()

        db = TestingSessionLocal(); _clean_db(db); db.close()
    finally:
        pass

def test_compare_versions():
    studio, project, media, replicas = _setup_project_with_replicas()
    try:
        resp1 = client.post(f"/api/v1/projects/{project.id}/rythmo/versions", json={"comment": "v1"}, headers=_auth_headers())
        v1_id = resp1.json()["id"]
        # Modifier et ajouter une réplique
        r1_id = replicas[0].id
        client.patch(f"/api/v1/replicas/{r1_id}", json={"text": "Bonjour modifié"}, headers=_auth_headers())
        # Ajouter une nouvelle réplique
        db = TestingSessionLocal()
        new_rep = Replica(id=uuid.uuid4(), media_id=media.id, text="Nouvelle réplique", start_ms=4000, end_ms=6000, order_index=2)
        db.add(new_rep); db.commit(); db.close()

        resp2 = client.post(f"/api/v1/projects/{project.id}/rythmo/versions", json={"comment": "v2"}, headers=_auth_headers())
        v2_id = resp2.json()["id"]

        # Comparer
        resp_cmp = client.get(f"/api/v1/projects/{project.id}/rythmo/versions/compare?from={v1_id}&to={v2_id}", headers=_auth_headers())
        assert resp_cmp.status_code == 200, resp_cmp.text
        data = resp_cmp.json()
        assert "added" in data
        assert "removed" in data
        assert "modified" in data
        assert data["summary"]["added_count"] == 1
        assert data["summary"]["modified_count"] == 1
        assert any(m["id"] == str(r1_id) for m in data["modified"])

        db = TestingSessionLocal(); _clean_db(db); db.close()
    finally:
        pass

def test_compare_by_version_numbers():
    studio, project, media, replicas = _setup_project_with_replicas()
    try:
        client.post(f"/api/v1/projects/{project.id}/rythmo/versions", json={}, headers=_auth_headers())
        r1_id = replicas[0].id
        client.patch(f"/api/v1/replicas/{r1_id}", json={"text": "changed"}, headers=_auth_headers())
        client.post(f"/api/v1/projects/{project.id}/rythmo/versions", json={}, headers=_auth_headers())

        resp = client.get(f"/api/v1/projects/{project.id}/rythmo/versions/compare?from_version=1&to_version=2", headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["from"]["version_number"] == 1
        assert resp.json()["to"]["version_number"] == 2

        db = TestingSessionLocal(); _clean_db(db); db.close()
    finally:
        pass

def test_restore_creates_correct_state_with_typo_codes():
    studio, project, media, replicas = _setup_project_with_replicas()
    try:
        # V1 sans typo
        v1 = client.post(f"/api/v1/projects/{project.id}/rythmo/versions", json={}, headers=_auth_headers()).json()
        # Modifier typo
        client.patch(f"/api/v1/replicas/{replicas[0].id}", json={"typo_codes": {"crochets": True}}, headers=_auth_headers())
        v2 = client.post(f"/api/v1/projects/{project.id}/rythmo/versions", json={}, headers=_auth_headers()).json()
        assert any(r.get("typo_codes", {}).get("crochets") for r in v2["snapshot"])

        # Restore v1 (sans typo)
        resp = client.post(f"/api/v1/projects/{project.id}/rythmo/versions/{v1['id']}/restore", headers=_auth_headers())
        assert resp.status_code == 200
        db = TestingSessionLocal()
        media_ids = [m.id for m in db.query(MediaAsset).filter(MediaAsset.project_id == project.id).all()]
        reps = db.query(Replica).filter(Replica.media_id.in_(media_ids)).all()
        assert not any((r.typo_codes or {}).get("crochets") for r in reps)
        db.close()
        db2 = TestingSessionLocal(); _clean_db(db2); db2.close()
    finally:
        pass
