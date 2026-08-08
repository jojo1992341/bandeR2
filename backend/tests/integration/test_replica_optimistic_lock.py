"""
Test d'intégration §16.4 — Verrouillage optimiste par réplique avec notification WebSocket.

Scénario :
  1. Deux utilisateurs (Camille et Denis) éditent la même réplique simultanément
  2. Camille acquiert le verrou → Denis ne peut pas l'acquérir (indicateur visuel)
  3. Camille modifie avec version=1 → succès, version devient 2
  4. Denis tente de modifier avec version=1 (périmée) → 409 Conflict
  5. Denis récupère la version actuelle (version=2), refait sa modification → succès
  6. Aucune écriture concurrente destructive ne s'est produite
  7. Camille relâche le verrou → Denis peut maintenant acquérir
"""

import uuid
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import get_db
from app.models import Base, Studio, Project, MediaAsset, Replica, User, StudioMembership

# SQLite in-memory pour les tests
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def _setup_project_and_replica():
    """Crée un studio, projet, média et une réplique de test."""
    db = TestingSessionLocal()
    try:
        studio = Studio(id=uuid.uuid4(), name="Test Studio Lock", plan="pro")
        db.add(studio)
        db.commit()
        db.refresh(studio)

        project = Project(
            id=uuid.uuid4(),
            studio_id=studio.id,
            title="Test Project Lock",
            source_lang="fr",
            target_lang="fr",
            status="draft",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        media = MediaAsset(
            id=uuid.uuid4(),
            project_id=project.id,
            storage_path="test/lock_video.mp4",
            status="confirmed",
        )
        db.add(media)
        db.commit()
        db.refresh(media)

        replica = Replica(
            id=uuid.uuid4(),
            media_id=media.id,
            speaker_id=None,
            text="Bonjour le monde",
            start_ms=0,
            end_ms=3000,
            order_index=0,
            typo_codes={},
            confidence_score=0.9,
            is_manually_edited=False,
            breath_marker=False,
            version=1,  # §16.4 — version initiale
        )
        db.add(replica)
        db.commit()
        db.refresh(replica)

        return {
            "studio_id": studio.id,
            "project_id": project.id,
            "media_id": media.id,
            "replica_id": replica.id,
            "replica_version": replica.version,
        }
    finally:
        db.close()


def _cleanup():
    db = TestingSessionLocal()
    try:
        db.query(Replica).delete()
        db.query(MediaAsset).delete()
        db.query(Project).delete()
        try:
            db.query(StudioMembership).delete()
        except Exception:
            pass
        db.query(Studio).delete()
        db.commit()
    finally:
        db.close()


# ── Tests ──────────────────────────────────────────────────────


def test_optimistic_lock_version_conflict_returns_409():
    """
    §16.4 — Deux utilisateurs éditent la même réplique simultanément :
    le second reçoit 409 Conflict car sa version est périmée.
    """
    fixture = _setup_project_and_replica()
    replica_id = fixture["replica_id"]

    try:
        # Camille lit la réplique (version=1)
        resp_get = client.get(f"/api/v1/replicas/{replica_id}")
        assert resp_get.status_code == 200
        camille_version = resp_get.json()["version"]
        assert camille_version == 1

        # Denis lit aussi la réplique (version=1)
        denis_version = camille_version  # même lecture

        # Camille modifie en premier avec version=1 → succès
        resp_camille = client.patch(
            f"/api/v1/replicas/{replica_id}",
            json={"text": "Bonsoir le monde", "version": camille_version},
        )
        assert resp_camille.status_code == 200, f"Camille's patch should succeed: {resp_camille.text}"
        camille_result = resp_camille.json()
        assert camille_result["version"] == 2, "Version should increment to 2"
        assert camille_result["replica"]["text"] == "Bonsoir le monde"
        assert camille_result["replica"]["version"] == 2

        # Denis tente de modifier avec version=1 (périmée) → 409 Conflict
        resp_denis = client.patch(
            f"/api/v1/replicas/{replica_id}",
            json={"text": "Salut le monde", "version": denis_version},
        )
        assert resp_denis.status_code == 409, f"Denis's patch should be rejected with 409: {resp_denis.text}"
        conflict = resp_denis.json()
        assert conflict["detail"]["code"] == "version_conflict"
        assert conflict["detail"]["current_version"] == 2
        assert conflict["detail"]["sent_version"] == 1

        # Vérifier que la réplique n'a pas été écrasée — texte de Camille reste
        resp_final = client.get(f"/api/v1/replicas/{replica_id}")
        assert resp_final.status_code == 200
        final = resp_final.json()
        assert final["text"] == "Bonsoir le monde", "No destructive concurrent write occurred"
        assert final["version"] == 2

    finally:
        _cleanup()


def test_optimistic_lock_correct_version_succeeds():
    """
    §16.4 — Après un conflit, Denis récupère la version actuelle
    et peut refaire sa modification avec la bonne version.
    """
    fixture = _setup_project_and_replica()
    replica_id = fixture["replica_id"]

    try:
        # Camille modifie (version=1 → version=2)
        client.patch(
            f"/api/v1/replicas/{replica_id}",
            json={"text": "Bonsoir le monde", "version": 1},
        )

        # Denis re-lit la réplique (version=2)
        resp = client.get(f"/api/v1/replicas/{replica_id}")
        current_version = resp.json()["version"]
        assert current_version == 2

        # Denis modifie avec la bonne version → succès
        resp_denis = client.patch(
            f"/api/v1/replicas/{replica_id}",
            json={"text": "Salut le monde", "version": current_version},
        )
        assert resp_denis.status_code == 200
        assert resp_denis.json()["version"] == 3
        assert resp_denis.json()["replica"]["text"] == "Salut le monde"

    finally:
        _cleanup()


def test_replica_lock_acquire_and_release():
    """
    §16.4 — Camille acquiert le verrou, Denis ne peut pas.
    Camille relâche, Denis peut alors acquérir.
    """
    from app.services.replica_lock_manager import lock_manager

    fixture = _setup_project_and_replica()
    replica_id = fixture["replica_id"]
    project_id = fixture["project_id"]
    camille_id = uuid.uuid4()
    denis_id = uuid.uuid4()

    try:
        # Camille acquiert le verrou
        resp = client.post(
            f"/api/v1/replicas/{replica_id}/lock",
            json={"user_id": str(camille_id), "user_name": "Camille"},
        )
        assert resp.status_code == 200
        assert resp.json()["acquired"] is True

        # Denis tente d'acquérir → refusé
        resp2 = client.post(
            f"/api/v1/replicas/{replica_id}/lock",
            json={"user_id": str(denis_id), "user_name": "Denis"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["acquired"] is False
        assert resp2.json()["locked_by"]["user_name"] == "Camille"

        # Statut du verrou
        resp_status = client.get(f"/api/v1/replicas/{replica_id}/lock")
        assert resp_status.status_code == 200
        assert resp_status.json()["locked"] is True
        assert resp_status.json()["user_name"] == "Camille"

        # Camille relâche le verrou
        resp_release = client.delete(
            f"/api/v1/replicas/{replica_id}/lock?user_id={camille_id}",
        )
        assert resp_release.status_code == 200
        assert resp_release.json()["released"] is True

        # Denis peut maintenant acquérir
        resp3 = client.post(
            f"/api/v1/replicas/{replica_id}/lock",
            json={"user_id": str(denis_id), "user_name": "Denis"},
        )
        assert resp3.status_code == 200
        assert resp3.json()["acquired"] is True

        # Cleanup
        lock_manager.release_lock(replica_id, denis_id)

    finally:
        # Force cleanup locks
        lock_manager._locks.clear()
        _cleanup()


def test_replica_lock_heartbeat_keeps_lock_alive():
    """
    §16.4 — Le heartbeat renouvelle le TTL du verrou.
    """
    from app.services.replica_lock_manager import lock_manager

    fixture = _setup_project_and_replica()
    replica_id = fixture["replica_id"]
    camille_id = uuid.uuid4()

    try:
        # Acquérir
        lock_manager.acquire_lock(replica_id, camille_id, "Camille", fixture["project_id"])

        # Heartbeat
        resp = client.post(
            f"/api/v1/replicas/{replica_id}/heartbeat",
            json={"user_id": str(camille_id)},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Vérifier que le verrou est toujours actif
        lock = lock_manager.get_lock(replica_id)
        assert lock is not None
        assert lock.user_name == "Camille"

        # Cleanup
        lock_manager.release_lock(replica_id, camille_id)

    finally:
        lock_manager._locks.clear()
        _cleanup()


def test_replica_lock_expired_allows_new_acquisition():
    """
    §16.4 — Un verrou expiré peut être acquis par un autre utilisateur.
    """
    import time
    from app.services.replica_lock_manager import lock_manager, LOCK_TTL_SECONDS

    fixture = _setup_project_and_replica()
    replica_id = fixture["replica_id"]
    camille_id = uuid.uuid4()
    denis_id = uuid.uuid4()

    try:
        # Camille acquiert le verrou
        success, _ = lock_manager.acquire_lock(replica_id, camille_id, "Camille", fixture["project_id"])
        assert success

        # Simuler l'expiration en modifiant last_heartbeat
        lock = lock_manager._locks[replica_id]
        lock.last_heartbeat = time.monotonic() - LOCK_TTL_SECONDS - 1  # expiré

        # Denis peut acquérir le verrou (l'ancien est expiré)
        success2, current = lock_manager.acquire_lock(replica_id, denis_id, "Denis", fixture["project_id"])
        assert success2

        # Cleanup
        lock_manager.release_lock(replica_id, denis_id)

    finally:
        lock_manager._locks.clear()
        _cleanup()


def test_patch_without_version_still_works():
    """
    §16.4 — Un PATCH sans version (client ancien) fonctionne toujours
    (pas de vérification de version si version non fournie).
    """
    fixture = _setup_project_and_replica()
    replica_id = fixture["replica_id"]

    try:
        # Patch sans version → succès (backward compatible)
        resp = client.patch(
            f"/api/v1/replicas/{replica_id}",
            json={"text": "Nouveau texte sans version"},
        )
        assert resp.status_code == 200
        assert resp.json()["replica"]["text"] == "Nouveau texte sans version"
        assert resp.json()["version"] == 2  # version incremented anyway

    finally:
        _cleanup()


def test_websocket_lock_snapshot_on_connect():
    """
    §16.4 — Un client WebSocket reçoit l'état des verrous du projet
    immédiatement à la connexion (lock_snapshot).
    """
    from app.services.replica_lock_manager import lock_manager

    fixture = _setup_project_and_replica()
    project_id = fixture["project_id"]
    replica_id = fixture["replica_id"]
    camille_id = uuid.uuid4()

    try:
        # Camille acquiert un verrou
        lock_manager.acquire_lock(replica_id, camille_id, "Camille", project_id)

        # Denis se connecte en WebSocket
        with client.websocket_connect(f"/api/v1/ws/projects/{project_id}/replicas") as ws:
            # Il doit recevoir le snapshot initial
            data = ws.receive_json()
            assert data["type"] == "lock_snapshot"
            assert str(replica_id) in data["locks"]
            assert data["locks"][str(replica_id)]["user_name"] == "Camille"

        # Cleanup
        lock_manager.release_lock(replica_id, camille_id)

    finally:
        lock_manager._locks.clear()
        _cleanup()


def test_full_concurrent_edit_scenario():
    """
    §16.4 — Test complet : deux utilisateurs, verrou + version conflict.
    Vérifie qu'un indicateur visuel de verrouillage apparaît et
    qu'aucune écriture concurrente destructive ne se produit.
    """
    from app.services.replica_lock_manager import lock_manager

    fixture = _setup_project_and_replica()
    replica_id = fixture["replica_id"]
    project_id = fixture["project_id"]
    camille_id = uuid.uuid4()
    denis_id = uuid.uuid4()

    try:
        # ── Étape 1 : Camille acquiert le verrou ──
        resp_lock_camille = client.post(
            f"/api/v1/replicas/{replica_id}/lock",
            json={"user_id": str(camille_id), "user_name": "Camille"},
        )
        assert resp_lock_camille.json()["acquired"] is True

        # ── Étape 2 : Denis tente d'acquérir le verrou → refusé ──
        resp_lock_denis = client.post(
            f"/api/v1/replicas/{replica_id}/lock",
            json={"user_id": str(denis_id), "user_name": "Denis"},
        )
        lock_result = resp_lock_denis.json()
        assert lock_result["acquired"] is False
        # Indicateur visuel : "Camille édite cette réplique"
        assert lock_result["locked_by"]["user_name"] == "Camille"
        assert lock_result["message"] == "Réplique verrouillée par Camille"

        # ── Étape 3 : Denis consulte le statut du verrou → voit Camille ──
        resp_status = client.get(f"/api/v1/replicas/{replica_id}/lock")
        assert resp_status.json()["locked"] is True
        assert resp_status.json()["user_name"] == "Camille"

        # ── Étape 4 : Camille modifie (version=1) → succès ──
        resp_patch_camille = client.patch(
            f"/api/v1/replicas/{replica_id}",
            json={"text": "Bonsoir le monde", "version": 1},
        )
        assert resp_patch_camille.status_code == 200
        assert resp_patch_camille.json()["version"] == 2

        # ── Étape 5 : Denis (avec ancienne version=1) tente de modifier → 409 ──
        resp_patch_denis = client.patch(
            f"/api/v1/replicas/{replica_id}",
            json={"text": "Salut le monde", "version": 1},
        )
        assert resp_patch_denis.status_code == 409

        # ── Étape 6 : Vérifier qu'aucune écriture destructive ne s'est produite ──
        resp_final = client.get(f"/api/v1/replicas/{replica_id}")
        final_data = resp_final.json()
        assert final_data["text"] == "Bonsoir le monde", \
            "Destructive write detected! Denis should not have overwritten Camille's edit"
        assert final_data["version"] == 2

        # ── Étape 7 : Camille relâche le verrou ──
        resp_release = client.delete(
            f"/api/v1/replicas/{replica_id}/lock?user_id={camille_id}",
        )
        assert resp_release.json()["released"] is True

        # ── Étape 8 : Denis peut maintenant acquérir et modifier ──
        resp_lock_denis2 = client.post(
            f"/api/v1/replicas/{replica_id}/lock",
            json={"user_id": str(denis_id), "user_name": "Denis"},
        )
        assert resp_lock_denis2.json()["acquired"] is True

        resp_patch_denis2 = client.patch(
            f"/api/v1/replicas/{replica_id}",
            json={"text": "Salut le monde", "version": 2},
        )
        assert resp_patch_denis2.status_code == 200
        assert resp_patch_denis2.json()["replica"]["text"] == "Salut le monde"
        assert resp_patch_denis2.json()["version"] == 3

        # Cleanup
        lock_manager.release_lock(replica_id, denis_id)

    finally:
        lock_manager._locks.clear()
        _cleanup()
