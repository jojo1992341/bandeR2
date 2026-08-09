import uuid
import pytest

# Réutiliser les fixtures du module split_merge pour partager le même engine SQLite in-memory
# et éviter les conflits d'override get_db entre fichiers
from .test_replica_split_merge import (
    TestingSessionLocal,
    client,
    _clean_db,
    _setup_fixture as _setup_split_fixture,
    engine,
    Base,
)
from app.models import Studio, Project, MediaAsset, Replica

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


def _setup_fixture():
    # Wrapper pour réutiliser la même logique mais avec un média dédié typo
    # On nettoie d'abord
    db = TestingSessionLocal()
    try:
        _clean_db(db)
        studio = Studio(id=uuid.uuid4(), name="Typo Studio", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Typo Project", source_lang="fr", target_lang="fr", status="draft")
        db.add(project); db.commit(); db.refresh(project)
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="test/video_typo.mp4", status="confirmed")
        db.add(media); db.commit(); db.refresh(media)
        return studio, project, media
    finally:
        db.close()

def test_patch_typo_codes_single_code():
    """§2.4 / §9.4 — appliquer un code typographique met à jour typo_codes côté API"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        rid = uuid.uuid4()
        rep = Replica(id=rid, media_id=media.id, text="Bonjour le monde", start_ms=0, end_ms=2000, order_index=0, typo_codes={})
        db.add(rep); db.commit(); db.close()

        # Appliquer italique (voix off)
        resp = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"italique": True}}, headers=_auth_headers())
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "updated"
        assert "typo_codes" in data
        assert data["typo_codes"].get("italique") is True

        # Vérifier via GET que c'est persisté
        resp2 = client.get(f"/api/v1/replicas/{rid}", headers=_auth_headers())
        assert resp2.status_code == 200
        rep2 = resp2.json()
        assert rep2["typo_codes"].get("italique") is True
        assert rep2["is_manually_edited"] is True

        # Vérifier en DB
        db2 = TestingSessionLocal()
        r = db2.query(Replica).filter(Replica.id == rid).first()
        assert r.typo_codes.get("italique") is True
        _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass

def test_patch_typo_codes_all_metier_codes():
    """Vérifie les 4 codes métier §2.4 : crochets, italique, majuscules, parentheses"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        rid = uuid.uuid4()
        rep = Replica(id=rid, media_id=media.id, text="Test cris", start_ms=0, end_ms=1500, order_index=0, typo_codes={})
        db.add(rep); db.commit(); db.close()

        # Crochets d'entrée/sortie
        resp = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"crochets": True}}, headers=_auth_headers())
        assert resp.status_code == 200
        assert client.get(f"/api/v1/replicas/{rid}", headers=_auth_headers()).json()["typo_codes"]["crochets"] is True

        # Italique voix off (alias)
        resp = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"italic": True}}, headers=_auth_headers())
        assert resp.status_code == 200
        data = client.get(f"/api/v1/replicas/{rid}", headers=_auth_headers()).json()
        # Doit merger avec crochets, pas écraser
        assert data["typo_codes"].get("crochets") is True
        assert data["typo_codes"].get("italique") is True

        # MAJUSCULES cris (alias majuscules / uppercase / cri)
        resp = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"majuscules": True}}, headers=_auth_headers())
        assert resp.status_code == 200
        data = client.get(f"/api/v1/replicas/{rid}", headers=_auth_headers()).json()
        assert data["typo_codes"]["majuscules"] is True
        assert data["typo_codes"]["crochets"] is True  # toujours présent

        # Parentheses indications de jeu
        resp = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"parentheses": True}}, headers=_auth_headers())
        assert resp.status_code == 200
        data = client.get(f"/api/v1/replicas/{rid}", headers=_auth_headers()).json()
        assert data["typo_codes"]["parentheses"] is True
        assert data["typo_codes"]["italique"] is True

        # Vérifier que toutes les 4 sont présentes
        assert len([k for k,v in data["typo_codes"].items() if v]) >= 4

        db2 = TestingSessionLocal(); _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass

def test_patch_typo_codes_merge_and_toggle():
    """Merger puis désactiver un code"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        rid = uuid.uuid4()
        rep = Replica(id=rid, media_id=media.id, text="Hello", start_ms=0, end_ms=1000, order_index=0, typo_codes={"crochets": True})
        db.add(rep); db.commit(); db.close()

        # Ajouter majuscules, doit merger
        resp = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"majuscules": True}}, headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["typo_codes"]["crochets"] is True
        assert resp.json()["typo_codes"]["majuscules"] is True

        # Désactiver crochets
        resp2 = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"crochets": False}}, headers=_auth_headers())
        assert resp2.status_code == 200
        data = resp2.json()["typo_codes"]
        # Après désactivation, crochets doit être False ou absent
        assert data.get("crochets") is False or "crochets" not in data
        assert data.get("majuscules") is True

        db2 = TestingSessionLocal(); _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass

def test_patch_typo_codes_alias_normalization():
    """Vérifie que les alias sont normalisés côté backend"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        rid = uuid.uuid4()
        rep = Replica(id=rid, media_id=media.id, text="Test", start_ms=0, end_ms=1000, order_index=0, typo_codes={})
        db.add(rep); db.commit(); db.close()

        # Utiliser alias anglais "brackets" doit être normalisé en "crochets"
        resp = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"brackets": True}}, headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["typo_codes"].get("crochets") is True

        # Alias "italic" -> "italique"
        resp = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"italic": True}}, headers=_auth_headers())
        assert resp.json()["typo_codes"].get("italique") is True

        # Alias "uppercase" -> "majuscules"
        resp = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"uppercase": True}}, headers=_auth_headers())
        assert resp.json()["typo_codes"].get("majuscules") is True

        # Alias "parentheses_jeu"
        resp = client.patch(f"/api/v1/replicas/{rid}", json={"typo_codes": {"parentheses_jeu": True}}, headers=_auth_headers())
        assert resp.json()["typo_codes"].get("parentheses") is True

        db2 = TestingSessionLocal(); _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass

def test_patch_typo_codes_persists_with_split_and_merge():
    """Les typo_codes doivent être conservés lors du split/merge §9.4"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        rid = uuid.uuid4()
        rep = Replica(id=rid, media_id=media.id, text="Bonjour le monde du doublage", start_ms=0, end_ms=4000, order_index=0, typo_codes={"italique": True, "crochets": True})
        db.add(rep); db.commit(); db.close()

        # Split
        resp = client.post(f"/api/v1/replicas/{rid}/split", json={"split_ms": 2000}, headers=_auth_headers())
        assert resp.status_code == 200
        r1, r2 = resp.json()["replicas"]
        assert r1["typo_codes"].get("italique") is True
        assert r2["typo_codes"].get("crochets") is True

        # Merge
        resp2 = client.post("/api/v1/replicas/merge", json={"replica_ids": [r1["id"], r2["id"]]}, headers=_auth_headers())
        assert resp2.status_code == 200
        merged = resp2.json()["replica"]
        assert merged["typo_codes"].get("italique") is True
        assert merged["typo_codes"].get("crochets") is True

        db2 = TestingSessionLocal(); _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass

def test_patch_typo_codes_invalid_not_found():
    fake = uuid.uuid4()
    resp = client.patch(f"/api/v1/replicas/{fake}", json={"typo_codes": {"italique": True}}, headers=_auth_headers())
    assert resp.status_code == 404

def test_get_replica_returns_typo_codes():
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        rid = uuid.uuid4()
        rep = Replica(id=rid, media_id=media.id, text="Test", start_ms=0, end_ms=1000, order_index=0, typo_codes={"majuscules": True})
        db.add(rep); db.commit(); db.close()

        resp = client.get(f"/api/v1/replicas/{rid}", headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["typo_codes"]["majuscules"] is True
        assert resp.json()["text"] == "Test"

        db2 = TestingSessionLocal(); _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass
