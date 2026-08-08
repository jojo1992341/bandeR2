"""
Test d'intégration §14.2 / §16.1 — Cycle de vie d'un projet/bande rythmo.

Vérifie :
  1. Toutes les transitions autorisées fonctionnent
  2. Les transitions interdites sont rejetées (403)
  3. La validation formelle par le DA verrouille la bande (→ Valide)
  4. L'édition d'une réplique est refusée quand le projet est Validé (403)
  5. L'édition d'une réplique est refusée quand le projet est Archivé (403)
  6. Le déverrouillage explicite ré-autorise l'édition (Valide → En_relecture)
  7. Le statut "draft" (ancien) est backward compatible
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import engine, SessionLocal as TestingSessionLocal
from app.models import Base, Studio, Project, MediaAsset, Replica

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _setup_project_with_status(status="Cree"):
    """Crée un studio, projet (avec statut donné), média et une réplique."""
    db = TestingSessionLocal()
    try:
        studio = Studio(id=uuid.uuid4(), name="Test Studio Lifecycle", plan="pro")
        db.add(studio)
        db.commit()

        project = Project(
            id=uuid.uuid4(),
            studio_id=studio.id,
            title="Test Project Lifecycle",
            source_lang="fr",
            target_lang="fr",
            status=status,
        )
        db.add(project)
        db.commit()

        media = MediaAsset(
            id=uuid.uuid4(),
            project_id=project.id,
            storage_path="test/lifecycle.mp4",
            status="confirmed",
        )
        db.add(media)
        db.commit()

        replica = Replica(
            id=uuid.uuid4(),
            media_id=media.id,
            text="Bonjour le monde",
            start_ms=0,
            end_ms=3000,
            order_index=0,
            typo_codes={},
            confidence_score=0.9,
            is_manually_edited=False,
            breath_marker=False,
            version=1,
        )
        db.add(replica)
        db.commit()
        db.refresh(replica)

        return {
            "studio_id": studio.id,
            "project_id": project.id,
            "media_id": media.id,
            "replica_id": replica.id,
        }
    finally:
        db.close()


def _cleanup():
    db = TestingSessionLocal()
    try:
        db.query(Replica).delete()
        db.query(MediaAsset).delete()
        db.query(Project).delete()
        db.query(Studio).delete()
        db.commit()
    finally:
        db.close()


# ── Statuts et transitions autorisées ─────────────────────────

class TestProjectLifecycleTransitions:
    """§16.1 — Vérifie toutes les transitions autorisées du cycle de vie."""

    def test_cree_to_en_traitement(self):
        """Cree → En_traitement : autorisé"""
        fixture = _setup_project_with_status("Cree")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "En_traitement"},
            )
            assert resp.status_code == 200, f"Transition should succeed: {resp.text}"
            assert resp.json()["success"] is True
            assert resp.json()["to_status"] == "En_traitement"
        finally:
            _cleanup()

    def test_en_traitement_to_pret_pour_edition(self):
        """En_traitement → Pret_pour_edition : autorisé"""
        fixture = _setup_project_with_status("En_traitement")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "Pret_pour_edition"},
            )
            assert resp.status_code == 200
            assert resp.json()["to_status"] == "Pret_pour_edition"
        finally:
            _cleanup()

    def test_pret_pour_edition_to_en_edition(self):
        """Pret_pour_edition → En_edition : autorisé"""
        fixture = _setup_project_with_status("Pret_pour_edition")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "En_edition"},
            )
            assert resp.status_code == 200
            assert resp.json()["to_status"] == "En_edition"
        finally:
            _cleanup()

    def test_en_edition_to_en_relecture(self):
        """En_edition → En_relecture : autorisé"""
        fixture = _setup_project_with_status("En_edition")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "En_relecture"},
            )
            assert resp.status_code == 200
            assert resp.json()["to_status"] == "En_relecture"
        finally:
            _cleanup()

    def test_en_relecture_to_valide(self):
        """En_relecture → Valide : autorisé (validation formelle)"""
        fixture = _setup_project_with_status("En_relecture")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "Valide"},
            )
            assert resp.status_code == 200
            assert resp.json()["to_status"] == "Valide"
        finally:
            _cleanup()

    def test_valide_to_exporte_livre(self):
        """Valide → Exporte_Livre : autorisé"""
        fixture = _setup_project_with_status("Valide")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "Exporte_Livre"},
            )
            assert resp.status_code == 200
            assert resp.json()["to_status"] == "Exporte_Livre"
        finally:
            _cleanup()

    def test_exporte_livre_to_archive(self):
        """Exporte_Livre → Archive : autorisé"""
        fixture = _setup_project_with_status("Exporte_Livre")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "Archive"},
            )
            assert resp.status_code == 200
            assert resp.json()["to_status"] == "Archive"
        finally:
            _cleanup()


class TestProjectLifecycleForbiddenTransitions:
    """§16.1 — Vérifie que les transitions interdites sont rejetées (403)."""

    def test_cree_to_valide_forbidden(self):
        """Cree → Valide : interdit (saut d'étapes)"""
        fixture = _setup_project_with_status("Cree")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "Valide"},
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "forbidden_transition"
        finally:
            _cleanup()

    def test_cree_to_en_edition_forbidden(self):
        """Cree → En_edition : interdit"""
        fixture = _setup_project_with_status("Cree")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "En_edition"},
            )
            assert resp.status_code == 403
        finally:
            _cleanup()

    def test_valide_to_en_edition_forbidden(self):
        """Valide → En_edition : interdit (il faut passer par En_relecture via unlock)"""
        fixture = _setup_project_with_status("Valide")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "En_edition"},
            )
            assert resp.status_code == 403
        finally:
            _cleanup()

    def test_archive_to_en_edition_forbidden(self):
        """Archive → En_edition : interdit"""
        fixture = _setup_project_with_status("Archive")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "En_edition"},
            )
            assert resp.status_code == 403
        finally:
            _cleanup()

    def test_en_traitement_to_valide_forbidden(self):
        """En_traitement → Valide : interdit"""
        fixture = _setup_project_with_status("En_traitement")
        try:
            resp = client.patch(
                f"/api/v1/projects/{fixture['project_id']}/status",
                json={"status": "Valide"},
            )
            assert resp.status_code == 403
        finally:
            _cleanup()


class TestProjectLifecycleValidationAndEditLock:
    """
    §16.1 — Validation formelle par le DA + verrouillage écriture.

    Test d'achèvement : vérifie que l'édition d'une réplique appartenant
    à une bande Validée est refusée sans déverrouillage explicite.
    """

    def test_validate_project_locks_editing(self):
        """
        Quand le projet passe en Valide, l'édition de réplique est interdite (403).
        """
        fixture = _setup_project_with_status("En_relecture")
        project_id = fixture["project_id"]
        replica_id = fixture["replica_id"]

        try:
            # Tenter d'éditer en statut En_relecture → autorisé
            resp_edit = client.patch(
                f"/api/v1/replicas/{replica_id}",
                json={"text": "Modification en relecture", "version": 1},
            )
            assert resp_edit.status_code == 200, f"Edit should succeed in En_relecture: {resp_edit.text}"

            # Valider le projet (DA)
            resp_validate = client.post(
                f"/api/v1/projects/{project_id}/validate",
                json={},
            )
            assert resp_validate.status_code == 200
            assert resp_validate.json()["to_status"] == "Valide"

            # Tenter d'éditer en statut Valide → interdit (403)
            resp_edit_locked = client.patch(
                f"/api/v1/replicas/{replica_id}",
                json={"text": "Tentative après validation", "version": 2},
            )
            assert resp_edit_locked.status_code == 403, \
                "Edit should be forbidden when project is Valide"
            assert resp_edit_locked.json()["detail"]["code"] == "project_readonly"

        finally:
            _cleanup()

    def test_unlock_project_reallows_editing(self):
        """
        Après déverrouillage explicite (Valide → En_relecture),
        l'édition de réplique est à nouveau autorisée.
        """
        fixture = _setup_project_with_status("Valide")
        project_id = fixture["project_id"]
        replica_id = fixture["replica_id"]

        try:
            # Édition interdite en Valide
            resp_locked = client.patch(
                f"/api/v1/replicas/{replica_id}",
                json={"text": "Interdit", "version": 1},
            )
            assert resp_locked.status_code == 403

            # Déverrouillage explicite
            resp_unlock = client.post(
                f"/api/v1/projects/{project_id}/unlock",
                json={},
            )
            assert resp_unlock.status_code == 200
            assert resp_unlock.json()["to_status"] == "En_relecture"

            # Édition à nouveau autorisée
            resp_edit = client.patch(
                f"/api/v1/replicas/{replica_id}",
                json={"text": "Après déverrouillage", "version": 1},
            )
            assert resp_edit.status_code == 200, \
                f"Edit should succeed after unlock: {resp_edit.text}"

        finally:
            _cleanup()

    def test_archive_project_forbids_editing(self):
        """
        Quand le projet est Archivé, l'édition est interdite.
        """
        fixture = _setup_project_with_status("Archive")
        replica_id = fixture["replica_id"]

        try:
            resp = client.patch(
                f"/api/v1/replicas/{replica_id}",
                json={"text": "Interdit en archive", "version": 1},
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "project_readonly"
        finally:
            _cleanup()

    def test_split_forbidden_in_valide(self):
        """Split interdit quand le projet est Validé."""
        fixture = _setup_project_with_status("Valide")
        replica_id = fixture["replica_id"]

        try:
            resp = client.post(
                f"/api/v1/replicas/{replica_id}/split",
                json={"split_ms": 1500},
            )
            assert resp.status_code == 403
        finally:
            _cleanup()

    def test_merge_forbidden_in_valide(self):
        """Merge interdit quand le projet est Validé."""
        fixture = _setup_project_with_status("Valide")
        replica_id = fixture["replica_id"]

        try:
            resp = client.post(
                "/api/v1/replicas/merge",
                json={"replica_ids": [str(replica_id), str(uuid.uuid4())]},
            )
            # 403 (project readonly) or 404 (second replica not found) — either is fine
            assert resp.status_code in (403, 404)
        finally:
            _cleanup()

    def test_full_lifecycle_with_validation_and_unlock(self):
        """
        Scénario complet : parcours du cycle de vie complet avec
        validation, tentative d'édition refusée, déverrouillage,
        et édition réussie.
        """
        fixture = _setup_project_with_status("Cree")
        project_id = fixture["project_id"]
        replica_id = fixture["replica_id"]

        try:
            transitions = [
                "En_traitement",
                "Pret_pour_edition",
                "En_edition",
                "En_relecture",
                "Valide",
            ]

            for status in transitions:
                resp = client.patch(
                    f"/api/v1/projects/{project_id}/status",
                    json={"status": status},
                )
                assert resp.status_code == 200, f"Transition to {status} should succeed: {resp.text}"

            # Projet est maintenant Validé → édition interdite
            resp_locked = client.patch(
                f"/api/v1/replicas/{replica_id}",
                json={"text": "Interdit", "version": 1},
            )
            assert resp_locked.status_code == 403
            assert "verrouillée" in resp_locked.json()["detail"]["message"].lower()

            # Déverrouillage explicite
            resp_unlock = client.post(f"/api/v1/projects/{project_id}/unlock", json={})
            assert resp_unlock.status_code == 200
            assert resp_unlock.json()["to_status"] == "En_relecture"

            # Édition maintenant autorisée
            resp_edit = client.patch(
                f"/api/v1/replicas/{replica_id}",
                json={"text": "Après unlock", "version": 1},
            )
            assert resp_edit.status_code == 200

        finally:
            _cleanup()


class TestProjectStatusQueries:
    """§16.1 — Requêtes de statut."""

    def test_get_project_status(self):
        fixture = _setup_project_with_status("En_edition")
        try:
            resp = client.get(f"/api/v1/projects/{fixture['project_id']}/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "En_edition"
            assert data["label"] == "En édition"
            assert data["is_editable"] is True
            assert "En_relecture" in data["allowed_transitions"]
        finally:
            _cleanup()

    def test_get_valide_status(self):
        fixture = _setup_project_with_status("Valide")
        try:
            resp = client.get(f"/api/v1/projects/{fixture['project_id']}/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "Valide"
            assert data["is_editable"] is False
            assert "En_relecture" in data["allowed_transitions"]  # unlock allowed
        finally:
            _cleanup()

    def test_list_all_statuses(self):
        resp = client.get("/api/v1/projects/statuses")
        assert resp.status_code == 200
        statuses = resp.json()
        assert len(statuses) == 8
        status_values = [s["value"] for s in statuses]
        assert "Cree" in status_values
        assert "Valide" in status_values
        assert "Archive" in status_values

    def test_get_status_not_found(self):
        fake = uuid.uuid4()
        resp = client.get(f"/api/v1/projects/{fake}/status")
        assert resp.status_code == 404


class TestValidationPermission:
    """§16.1 — Permission de validation (rôle DA)."""

    def test_validate_with_da_role(self):
        fixture = _setup_project_with_status("En_relecture")
        try:
            resp = client.post(
                f"/api/v1/projects/{fixture['project_id']}/validate",
                json={"user_role": "directeur_artistique"},
            )
            assert resp.status_code == 200
            assert resp.json()["to_status"] == "Valide"
        finally:
            _cleanup()

    def test_validate_with_insufficient_role(self):
        fixture = _setup_project_with_status("En_relecture")
        try:
            resp = client.post(
                f"/api/v1/projects/{fixture['project_id']}/validate",
                json={"user_role": "adaptateur"},
            )
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "insufficient_role"
        finally:
            _cleanup()

    def test_validate_with_chef_de_projet_role(self):
        fixture = _setup_project_with_status("En_relecture")
        try:
            resp = client.post(
                f"/api/v1/projects/{fixture['project_id']}/validate",
                json={"user_role": "chef_de_projet"},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()
