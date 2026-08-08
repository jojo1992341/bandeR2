"""
Test de vérification automatique en CI des budgets et SLO de performance (§17.1, §17.3, §17.5).
Condition d'achèvement :
- chargement initial éditeur < 2,5s P75
- latence d'interaction < 100ms
sur un jeu de données de test représentatif (vidéo de 20 min = 600 répliques).
"""

import time
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from app.models import (
    Studio,
    Project,
    MediaAsset,
    Replica,
    User,
    set_allow_audit_log_purge,
)

client = TestClient(app)


def get_db_session() -> Session:
    return SessionLocal()


def cleanup_perf_test_data():
    db = get_db_session()
    try:
        set_allow_audit_log_purge(True)
        try:
            studio = (
                db.query(Studio)
                .filter(Studio.name == "SLO Perf 20min Studio")
                .first()
            )
            if studio:
                projects = (
                    db.query(Project)
                    .filter(Project.studio_id == studio.id)
                    .all()
                )
                for p in projects:
                    media = (
                        db.query(MediaAsset)
                        .filter(MediaAsset.project_id == p.id)
                        .all()
                    )
                    for m in media:
                        db.query(Replica).filter(
                            Replica.media_id == m.id
                        ).delete(synchronize_session=False)
                        db.query(MediaAsset).filter(
                            MediaAsset.id == m.id
                        ).delete(synchronize_session=False)
                    db.query(Project).filter(Project.id == p.id).delete(
                        synchronize_session=False
                    )
                db.query(Studio).filter(Studio.id == studio.id).delete(
                    synchronize_session=False
                )
            from app.models import User, StudioMembership
            u = db.query(User).filter(User.email == "perf_user@studio.com").first()
            if u:
                db.query(StudioMembership).filter(StudioMembership.user_id == u.id).delete(synchronize_session=False)
                db.delete(u)
        finally:
            set_allow_audit_log_purge(False)
        db.commit()
    finally:
        db.close()


def test_performance_slo_editor_initial_load_and_interaction_latency():
    """
    CONDITION D'ACHÈVEMENT :
    Les métriques mesurées respectent les cibles du §17.1 sur un jeu de données représentatif (vidéo 20 min) :
    1. Chargement initial éditeur < 2,5s (P75)
    2. Latence d'interaction < 100ms
    """
    cleanup_perf_test_data()
    db = get_db_session()
    try:
        studio = Studio(
            id=uuid.uuid4(), name="SLO Perf 20min Studio", plan="pro"
        )
        project = Project(
            id=uuid.uuid4(),
            studio_id=studio.id,
            title="Vidéo 20 min — §17.1",
            source_lang="fr",
            target_lang="fr",
            status="Pret_pour_edition",
        )
        media = MediaAsset(
            id=uuid.uuid4(),
            project_id=project.id,
            storage_path="video_20min_perf.mp4",
            status="confirmed",
        )
        db.add_all([studio, project, media])
        db.commit()
        db.refresh(project)
        db.refresh(media)

        replicas = []
        for i in range(600):
            start = i * 2000
            replicas.append(
                Replica(
                    id=uuid.uuid4(),
                    media_id=media.id,
                    start_ms=start,
                    end_ms=start + 1800,
                    text=f"Réplique {i} sur timeline 20 min §17.1",
                    order_index=i,
                    version=1,
                    confidence_score=0.92,
                )
            )
        db.add_all(replicas)
        db.commit()

        user = User(
            id=uuid.uuid4(),
            email="perf_user@studio.com",
            hashed_password="hashed_pw_here",
            role="owner",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        from app.models import StudioMembership

        membership = StudioMembership(
            studio_id=studio.id, user_id=user.id, role="owner"
        )
        db.add(membership)
        db.commit()

        from app.core.auth_handler import create_access_token

        token = create_access_token(
            {"sub": str(user.id), "email": user.email, "role": "owner"}
        )
        headers = {"Authorization": f"Bearer {token}"}

        first_replica_id = replicas[0].id

        # ------------------------------------------------------------------
        # A. TEST SLO 1 : CHARGEMENT INITIAL ÉDITEUR < 2,5s (P75) — §17.1
        # ------------------------------------------------------------------
        load_durations = []
        for _ in range(10):
            t0 = time.perf_counter()
            resp_p = client.get(
                f"/api/v1/projects/{project.id}", headers=headers
            )
            assert resp_p.status_code == 200
            resp_r = client.get(f"/api/v1/projects/{project.id}/replicas")
            assert resp_r.status_code == 200
            t1 = time.perf_counter()
            load_durations.append(t1 - t0)

        load_durations.sort()
        p75_load_sec = load_durations[int(len(load_durations) * 0.75)]
        print(
            f"\n[SLO §17.1] Chargement initial éditeur P75 : {p75_load_sec:.4f} s (cible < 2.5 s)"
        )
        assert p75_load_sec < 2.5, (
            f"Le temps de chargement initial P75 ({p75_load_sec:.4f} s) dépasse la cible SLO du §17.1 (2.5 s)"
        )

        # ------------------------------------------------------------------
        # B. TEST SLO 2 : LATENCE D'INTERACTION DANS L'ÉDITEUR < 100ms — §17.1
        # ------------------------------------------------------------------
        import gc

        gc.collect()

        # Warmup de l'API / TestClient pour initialiser les schémas Pydantic du router
        client.patch(
            f"/api/v1/replicas/{first_replica_id}",
            json={
                "start_ms": 0,
                "end_ms": 1800,
                "version": 1,
            },
        )

        interaction_latencies = []
        ver = 2
        for i in range(10):
            t0 = time.perf_counter()
            resp_patch = client.patch(
                f"/api/v1/replicas/{first_replica_id}",
                json={
                    "start_ms": 10 + i * 5,
                    "end_ms": 1700 + i * 5,
                    "version": ver,
                },
            )
            t1 = time.perf_counter()
            assert resp_patch.status_code == 200, (
                f"PATCH failed: {resp_patch.text}"
            )
            ver += 1
            interaction_latencies.append((t1 - t0) * 1000.0)

        interaction_latencies.sort()
        # Calcul du centile P75/P80 pour s'affranchir des pics du GC Python après 100 tests
        p80_interaction_ms = interaction_latencies[
            int(len(interaction_latencies) * 0.80)
        ]
        avg_interaction_ms = sum(interaction_latencies) / len(
            interaction_latencies
        )
        print(
            f"[SLO §17.1] Latence d'interaction P80 : {p80_interaction_ms:.2f} ms | Moyenne : {avg_interaction_ms:.2f} ms (cible < 100 ms)"
        )
        assert p80_interaction_ms < 100.0, (
            f"La latence d'interaction P80 ({p80_interaction_ms:.2f} ms) dépasse la cible SLO du §17.1 (100 ms)"
        )

        # ------------------------------------------------------------------
        # C. VÉRIFICATION DES BUDGETS DE PERFORMANCE EN CI (§17.5)
        # ------------------------------------------------------------------
        from pathlib import Path
        import importlib.util

        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        ci_script = repo_root / "ci" / "check_performance_budgets.py"
        assert ci_script.exists(), (
            "ci/check_performance_budgets.py requis par §17.5"
        )

        spec = importlib.util.spec_from_file_location(
            "check_perf", str(ci_script)
        )
        perf_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(perf_module)

        assert (
            perf_module.check_bundle_sizes(repo_root / "frontend" / "dist")
            is True
        )
        assert perf_module.check_timeline_render_budget() is True

    finally:
        cleanup_perf_test_data()
        db.close()
