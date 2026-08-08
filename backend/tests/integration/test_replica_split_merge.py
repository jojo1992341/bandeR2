import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import get_db
from app.models import Base, Studio, Project, MediaAsset, Replica, RythmoVersion

# Utiliser SQLite in-memory pour l'intégration sans dépendance Postgres
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)

# Créer le schéma une fois
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def _clean_db(db):
    # Supprimer dans l'ordre pour respecter FK
    try:
        db.query(RythmoVersion).delete()
    except:
        pass
    db.query(Replica).delete()
    db.query(MediaAsset).delete()
    db.query(Project).delete()
    db.query(Studio).delete()
    db.commit()

def _setup_fixture():
    db = TestingSessionLocal()
    try:
        _clean_db(db)
        studio = Studio(id=uuid.uuid4(), name="Test Studio SplitMerge", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Test Project", source_lang="fr", target_lang="fr", status="draft")
        db.add(project); db.commit(); db.refresh(project)
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="test/video.mp4", status="confirmed")
        db.add(media); db.commit(); db.refresh(media)
        return studio, project, media
    finally:
        db.close()

def test_split_produces_two_coherent_replicas():
    """§10.2 POST /replicas/{id}/split → deux Replica cohérentes en timing"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        # Créer une réplique initiale 0-4000 ms
        replica_id = uuid.uuid4()
        replica = Replica(
            id=replica_id,
            media_id=media.id,
            speaker_id=None,
            text="Bonjour le monde du doublage",
            start_ms=0,
            end_ms=4000,
            order_index=0,
            typo_codes={},
            confidence_score=0.9,
            is_manually_edited=False,
            breath_marker=False,
        )
        db.add(replica); db.commit(); db.refresh(replica)
        db.close()

        # Appel split au milieu (2000 ms)
        resp = client.post(f"/api/v1/replicas/{replica_id}/split", json={"split_ms": 2000})
        assert resp.status_code == 200, f"split failed: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data["status"] == "split"
        assert "replicas" in data and len(data["replicas"]) == 2

        r1, r2 = data["replicas"][0], data["replicas"][1]
        # Vérification cohérence timing
        assert r1["start_ms"] == 0, f"r1 start attendu 0, got {r1['start_ms']}"
        assert r1["end_ms"] == 2000, f"r1 end attendu 2000, got {r1['end_ms']}"
        assert r2["start_ms"] == 2000, f"r2 start attendu 2000, got {r2['start_ms']}"
        assert r2["end_ms"] == 4000, f"r2 end attendu 4000, got {r2['end_ms']}"
        # Aucun chevauchement, continuité
        assert r1["end_ms"] == r2["start_ms"]
        # Media cohérent
        assert r1["media_id"] == str(media.id)
        assert r2["media_id"] == str(media.id)
        # Texte réparti (pas vide, concat ≈ original)
        assert r1["text"].strip() != ""
        assert r2["text"].strip() != ""
        combined = (r1["text"] + " " + r2["text"]).strip()
        # Vérifier que tous les mots originaux sont présents (ordre conservé)
        orig_words = set("Bonjour le monde du doublage".split())
        combined_words = set(combined.split())
        assert orig_words == combined_words, f"mots manquants: {orig_words - combined_words}"

        # Vérifier en DB qu'il y a bien 2 répliques au total
        db2 = TestingSessionLocal()
        count = db2.query(Replica).filter(Replica.media_id == media.id).count()
        db2.close()
        assert count == 2, f"après split on attend 2 répliques, trouvé {count}"

        # Vérifier order_index cohérent
        assert r1["order_index"] == 0
        assert r2["order_index"] == 1

        # Nettoyage
        db3 = TestingSessionLocal()
        _clean_db(db3)
        db3.close()
    finally:
        try:
            db.close()
        except:
            pass

def test_split_default_midpoint():
    """Split sans split_ms doit couper au milieu temporel"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        rid = uuid.uuid4()
        rep = Replica(id=rid, media_id=media.id, text="Une phrase de test pour le split", start_ms=1000, end_ms=5000, order_index=0)
        db.add(rep); db.commit(); db.close()

        resp = client.post(f"/api/v1/replicas/{rid}/split", json={})
        assert resp.status_code == 200
        j = resp.json()
        r1, r2 = j["replicas"]
        assert r1["start_ms"] == 1000
        assert r2["end_ms"] == 5000
        assert r1["end_ms"] == r2["start_ms"] == 3000  # milieu de 1000-5000

        db2 = TestingSessionLocal(); _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass

def test_split_validation_out_of_bounds():
    """split_ms hors intervalle → 422"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        rid = uuid.uuid4()
        rep = Replica(id=rid, media_id=media.id, text="test", start_ms=0, end_ms=1000, order_index=0)
        db.add(rep); db.commit(); db.close()

        resp = client.post(f"/api/v1/replicas/{rid}/split", json={"split_ms": 0})
        assert resp.status_code == 422
        resp2 = client.post(f"/api/v1/replicas/{rid}/split", json={"split_ms": 1000})
        assert resp2.status_code == 422
        resp3 = client.post(f"/api/v1/replicas/{rid}/split", json={"split_ms": 5000})
        assert resp3.status_code == 422

        db2 = TestingSessionLocal(); _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass

def test_merge_produces_single_coherent_replica():
    """§10.2 POST /replicas/merge → une seule Replica cohérente"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        # Créer deux répliques contiguës
        r1_id = uuid.uuid4()
        r2_id = uuid.uuid4()
        r1 = Replica(id=r1_id, media_id=media.id, text="Bonjour le monde", start_ms=0, end_ms=2000, order_index=0)
        r2 = Replica(id=r2_id, media_id=media.id, text="du doublage", start_ms=2000, end_ms=4000, order_index=1)
        db.add_all([r1, r2]); db.commit(); db.close()

        resp = client.post("/api/v1/replicas/merge", json={"replica_ids": [str(r1_id), str(r2_id)]})
        assert resp.status_code == 200, f"merge failed: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data["status"] == "merged"
        assert data["merged_count"] == 2
        merged = data["replica"]
        assert merged["start_ms"] == 0
        assert merged["end_ms"] == 4000
        # Texte concaténé contient les deux
        assert "Bonjour" in merged["text"]
        assert "doublage" in merged["text"]
        # Ordre
        assert merged["order_index"] == 0
        # Vérifier en DB : 1 seule réplique
        db2 = TestingSessionLocal()
        count = db2.query(Replica).filter(Replica.media_id == media.id).count()
        assert count == 1, f"après merge on attend 1 réplique, trouvé {count}"
        remaining = db2.query(Replica).filter(Replica.media_id == media.id).first()
        assert remaining.start_ms == 0 and remaining.end_ms == 4000
        _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass

def test_merge_and_split_cycle():
    """Cycle complet : 1 → split → 2 → merge → 1 avec cohérence timing"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        rid = uuid.uuid4()
        rep = Replica(id=rid, media_id=media.id, text="Phrase complète à scinder puis fusionner", start_ms=0, end_ms=6000, order_index=0)
        db.add(rep); db.commit(); db.close()

        # Split à 2500
        resp_split = client.post(f"/api/v1/replicas/{rid}/split", json={"split_ms": 2500})
        assert resp_split.status_code == 200
        r1, r2 = resp_split.json()["replicas"]
        assert r1["end_ms"] == 2500 and r2["start_ms"] == 2500

        # Merge des deux
        resp_merge = client.post("/api/v1/replicas/merge", json={"replica_ids": [r1["id"], r2["id"]]})
        assert resp_merge.status_code == 200
        merged = resp_merge.json()["replica"]
        assert merged["start_ms"] == 0
        assert merged["end_ms"] == 6000
        assert merged["text"].strip() != ""

        db2 = TestingSessionLocal()
        assert db2.query(Replica).filter(Replica.media_id == media.id).count() == 1
        _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass

def test_merge_validation_different_media():
    """Fusion de répliques de médias différents → 422"""
    studio, project, media = _setup_fixture()
    db = TestingSessionLocal()
    try:
        media2 = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="test2.mp4", status="confirmed")
        db.add(media2); db.commit(); db.refresh(media2)

        r1_id = uuid.uuid4(); r2_id = uuid.uuid4()
        r1 = Replica(id=r1_id, media_id=media.id, text="a", start_ms=0, end_ms=1000, order_index=0)
        r2 = Replica(id=r2_id, media_id=media2.id, text="b", start_ms=0, end_ms=1000, order_index=0)
        db.add_all([r1, r2]); db.commit(); db.close()

        resp = client.post("/api/v1/replicas/merge", json={"replica_ids": [str(r1_id), str(r2_id)]})
        assert resp.status_code == 422

        db2 = TestingSessionLocal(); _clean_db(db2); db2.close()
    finally:
        try: db.close()
        except: pass

def test_split_not_found():
    fake = uuid.uuid4()
    resp = client.post(f"/api/v1/replicas/{fake}/split", json={"split_ms": 500})
    assert resp.status_code == 404
