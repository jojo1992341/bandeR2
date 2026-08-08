"""
Test d'intégration §14.2.1 — Dashboard.

E2E test vérifiant l'affichage correct des indicateurs
pour un studio disposant de plusieurs projets à statuts variés.

Scénario :
  1. Créer un studio avec 6 projets à statuts variés (Cree, En_traitement, En_edition, En_relecture, Valide, Archive)
  2. Associer des jobs pipeline à certains projets
  3. Appeler GET /studios/{id}/dashboard
  4. Vérifier :
     - Chaque projet apparaît avec son statut correct
     - Les indicateurs studio sont corrects (total, volume, répartition)
     - Le quota est calculé
  5. Filtrer par statut via GET /studios/{id}/projects?status=Valide
  6. Vérifier le filtrage
"""

import uuid
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import get_db
from app.models import Base, Studio, Project, PipelineJob, MediaAsset

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


def _setup_studio_with_varied_projects():
    """
    Crée un studio avec 6 projets à statuts variés et des jobs pipeline.
    """
    db = TestingSessionLocal()
    try:
        studio = Studio(
            id=uuid.uuid4(),
            name="Studio RythmoAI",
            plan="pro",
            quotas={"ai_minutes_limit": 600, "ai_minutes_used": 180},
        )
        db.add(studio)
        db.commit()

        now = datetime.now(timezone.utc)

        projects_data = [
            ("Projet Alpha", "Cree", now - timedelta(days=5)),
            ("Projet Beta", "En_traitement", now - timedelta(days=4)),
            ("Projet Gamma", "En_edition", now - timedelta(days=3)),
            ("Projet Delta", "En_relecture", now - timedelta(days=2)),
            ("Projet Epsilon", "Valide", now - timedelta(days=1)),
            ("Projet Zeta", "Archive", now - timedelta(hours=12)),
        ]

        created = []
        for title, status, updated_at in projects_data:
            proj = Project(
                id=uuid.uuid4(),
                studio_id=studio.id,
                title=title,
                source_lang="fr",
                target_lang="fr",
                status=status,
            )
            db.add(proj)
            db.flush()
            created.append((proj, status, updated_at))

        db.commit()

        # Add pipeline jobs
        # Projet Beta (En_traitement) — job in progress
        beta = created[1][0]
        job_progress = PipelineJob(
            id=uuid.uuid4(),
            project_id=beta.id,
            status="processing",
            progress_percent=64,
            current_step="diarisation",
            updated_at=now,
        )
        db.add(job_progress)

        # Projet Gamma (En_edition) — job completed
        gamma = created[2][0]
        job_done = PipelineJob(
            id=uuid.uuid4(),
            project_id=gamma.id,
            status="completed",
            progress_percent=100,
            current_step="export",
            updated_at=now - timedelta(hours=6),
        )
        db.add(job_done)

        # Projet Delta (En_relecture) — job completed
        delta = created[3][0]
        job_done2 = PipelineJob(
            id=uuid.uuid4(),
            project_id=delta.id,
            status="completed",
            progress_percent=100,
            current_step="export",
            updated_at=now - timedelta(hours=18),
        )
        db.add(job_done2)

        # Projet Epsilon (Valide) — job completed
        epsilon = created[4][0]
        job_done3 = PipelineJob(
            id=uuid.uuid4(),
            project_id=epsilon.id,
            status="completed",
            progress_percent=100,
            current_step="export",
            updated_at=now - timedelta(days=1),
        )
        db.add(job_done3)

        db.commit()

        return {
            "studio_id": studio.id,
            "projects": [(str(p.id), p.title, status) for p, status, _ in created],
        }
    finally:
        db.close()


def _cleanup():
    db = TestingSessionLocal()
    try:
        db.query(PipelineJob).delete()
        db.query(MediaAsset).delete()
        db.query(Project).delete()
        db.query(Studio).delete()
        db.commit()
    finally:
        db.close()


# ── Tests ──────────────────────────────────────────────────────


class TestDashboardIndicators:
    """§14.2.1 — Indicateurs studio affichés correctement."""

    def test_dashboard_returns_all_projects_with_correct_status(self):
        """
        Le dashboard affiche tous les projets du studio avec leur statut.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/dashboard")
            assert resp.status_code == 200, f"Dashboard should load: {resp.text}"
            data = resp.json()

            # 6 projets
            assert len(data["projects"]) == 6

            # Vérifier les statuts
            statuses = {p["status"] for p in data["projects"]}
            assert "Cree" in statuses
            assert "En_traitement" in statuses
            assert "En_edition" in statuses
            assert "En_relecture" in statuses
            assert "Valide" in statuses
            assert "Archive" in statuses

        finally:
            _cleanup()

    def test_dashboard_indicators_total_projects(self):
        """
        L'indicateur total_projects est correct.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/dashboard")
            data = resp.json()
            assert data["indicators"]["total_projects"] == 6
        finally:
            _cleanup()

    def test_dashboard_indicators_status_distribution(self):
        """
        La répartition par statut est correcte.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/dashboard")
            data = resp.json()
            dist = data["indicators"]["status_distribution"]

            # Chaque statut a count=1 (un projet par statut)
            dist_map = {d["status"]: d["count"] for d in dist}
            assert dist_map["Cree"] == 1
            assert dist_map["En_traitement"] == 1
            assert dist_map["En_edition"] == 1
            assert dist_map["En_relecture"] == 1
            assert dist_map["Valide"] == 1
            assert dist_map["Archive"] == 1

            # Labels en français
            dist_labels = {d["status"]: d["label"] for d in dist}
            assert dist_labels["Cree"] == "Créé"
            assert dist_labels["En_traitement"] == "En traitement"
            assert dist_labels["Valide"] == "Validé"

        finally:
            _cleanup()

    def test_dashboard_indicators_volume_month(self):
        """
        Volume traité dans le mois (projets ayant atteint Pret_pour_edition ou au-delà).
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/dashboard")
            data = resp.json()

            # Projets en édition, relecture, validé, archive = 4
            # (Cree et En_traitement ne comptent pas comme "traités")
            assert data["indicators"]["volume_month"] >= 4
        finally:
            _cleanup()

    def test_dashboard_indicators_quota(self):
        """
        Le quota IA restant est calculé correctement.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/dashboard")
            data = resp.json()
            quota = data["indicators"]["quota"]

            assert quota["limit_minutes"] == 600
            assert quota["remaining_minutes"] > 0
            assert 0 <= quota["percent_used"] <= 100
        finally:
            _cleanup()

    def test_dashboard_pipeline_progress_displayed(self):
        """
        L'avancement pipeline est affiché pour chaque projet.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/dashboard")
            data = resp.json()

            # Trouver le projet en traitement (Beta)
            beta = next(p for p in data["projects"] if p["status"] == "En_traitement")
            assert beta["pipeline"] is not None
            assert beta["pipeline"]["status"] == "processing"
            assert beta["pipeline"]["progress_percent"] == 64
            assert beta["pipeline"]["current_step"] == "diarisation"

            # Trouver le projet validé (Epsilon) — pipeline completed
            epsilon = next(p for p in data["projects"] if p["status"] == "Valide")
            assert epsilon["pipeline"] is not None
            assert epsilon["pipeline"]["status"] == "completed"

            # Projet Cree — pas de pipeline
            alpha = next(p for p in data["projects"] if p["status"] == "Cree")
            assert alpha["pipeline"] is None

        finally:
            _cleanup()

    def test_dashboard_last_modification_dates(self):
        """
        La dernière modification est affichée pour chaque projet.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/dashboard")
            data = resp.json()

            for p in data["projects"]:
                assert "updated_at" in p
                # updated_at should be an ISO string or null
                if p["updated_at"]:
                    # Should be parseable as ISO date
                    datetime.fromisoformat(p["updated_at"])

        finally:
            _cleanup()


class TestDashboardFilters:
    """§14.2.1 — Filtres par statut."""

    def test_filter_by_single_status(self):
        """
        Filtrer par statut unique retourne seulement les projets correspondants.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/projects?status=Valide")
            assert resp.status_code == 200
            data = resp.json()

            assert data["total"] == 1
            assert len(data["projects"]) == 1
            assert data["projects"][0]["status"] == "Valide"

        finally:
            _cleanup()

    def test_filter_by_multiple_statuses(self):
        """
        Filtrer par plusieurs statuts (séparés par virgule).
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/projects?statuses=Valide,En_edition,Archive")
            assert resp.status_code == 200
            data = resp.json()

            assert data["total"] == 3
            statuses = {p["status"] for p in data["projects"]}
            assert statuses == {"Valide", "En_edition", "Archive"}

        finally:
            _cleanup()

    def test_filter_returns_empty_for_unknown_status(self):
        """
        Filtrer par un statut inexistant retourne 0 projets.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/projects?status=NonExistent")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
        finally:
            _cleanup()

    def test_no_filter_returns_all_projects(self):
        """
        Sans filtre, tous les projets sont retournés.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/projects")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 6
        finally:
            _cleanup()

    def test_pagination(self):
        """
        La pagination fonctionne correctement.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/projects?per_page=2&page=1")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["projects"]) == 2
            assert data["total"] == 6
            assert data["total_pages"] == 3
        finally:
            _cleanup()


class TestDashboardStudioNotFound:
    """§14.2.1 — Erreur si studio inexistant."""

    def test_dashboard_404_for_unknown_studio(self):
        fake = uuid.uuid4()
        resp = client.get(f"/api/v1/studios/{fake}/dashboard")
        assert resp.status_code == 404

    def test_projects_404_for_unknown_studio(self):
        fake = uuid.uuid4()
        resp = client.get(f"/api/v1/studios/{fake}/projects")
        assert resp.status_code == 404


class TestDashboardE2E:
    """
    §14.2.1 — E2E : affichage correct des indicateurs pour un studio
    disposant de plusieurs projets à statuts variés.
    """

    def test_full_dashboard_e2e(self):
        """
        Scénario E2E complet : vérifie l'ensemble du dashboard
        pour un studio avec 6 projets à statuts variés.
        """
        fixture = _setup_studio_with_varied_projects()
        studio_id = fixture["studio_id"]

        try:
            # ── 1. Charger le dashboard ──
            resp = client.get(f"/api/v1/studios/{studio_id}/dashboard")
            assert resp.status_code == 200
            data = resp.json()

            # ── 2. Vérifier les infos studio ──
            assert data["studio_name"] == "Studio RythmoAI"
            assert data["studio_plan"] == "pro"

            # ── 3. Vérifier 6 projets affichés ──
            projects = data["projects"]
            assert len(projects) == 6

            # ── 4. Vérifier chaque statut représenté ──
            project_map = {p["status"]: p for p in projects}
            assert set(project_map.keys()) == {
                "Cree", "En_traitement", "En_edition",
                "En_relecture", "Valide", "Archive",
            }

            # ── 5. Vérifier les labels en français ──
            assert project_map["Cree"]["status_label"] == "Créé"
            assert project_map["En_traitement"]["status_label"] == "En traitement"
            assert project_map["Valide"]["status_label"] == "Validé"
            assert project_map["Archive"]["status_label"] == "Archivé"

            # ── 6. Vérifier pipeline avancement ──
            assert project_map["En_traitement"]["pipeline"]["progress_percent"] == 64
            assert project_map["En_traitement"]["pipeline"]["current_step"] == "diarisation"
            assert project_map["En_edition"]["pipeline"]["status"] == "completed"

            # ── 7. Vérifier les indicateurs ──
            ind = data["indicators"]
            assert ind["total_projects"] == 6
            assert ind["volume_month"] >= 4  # au moins 4 projets "traités"

            # Répartition
            dist = {d["status"]: d for d in ind["status_distribution"]}
            assert all(d["count"] == 1 for d in ind["status_distribution"])

            # Quota
            assert ind["quota"]["limit_minutes"] == 600
            assert ind["quota"]["remaining_minutes"] > 0

            # ── 8. Vérifier filtres disponibles ──
            assert len(data["filters"]) == 8
            filter_values = [f["value"] for f in data["filters"]]
            assert "Valide" in filter_values
            assert "Archive" in filter_values

            # ── 9. Filtrer par statut ──
            resp_filtered = client.get(
                f"/api/v1/studios/{studio_id}/projects?status=Valide"
            )
            filtered_data = resp_filtered.json()
            assert filtered_data["total"] == 1
            assert filtered_data["projects"][0]["status"] == "Valide"
            assert filtered_data["projects"][0]["status_label"] == "Validé"

            # ── 10. Filtrer par plusieurs statuts ──
            resp_multi = client.get(
                f"/api/v1/studios/{studio_id}/projects?statuses=Valide,En_edition,Archive"
            )
            multi_data = resp_multi.json()
            assert multi_data["total"] == 3

        finally:
            _cleanup()
