import uuid
import time
import pytest
from app.models import Studio, Project, MediaAsset, Replica, Export
from .test_replica_split_merge import TestingSessionLocal, client, _clean_db

def _setup_project_with_replicas_for_quality():
    db = TestingSessionLocal()
    try:
        _clean_db(db)
        try:
            db.query(Export).delete()
            db.commit()
        except:
            db.rollback()
        studio = Studio(id=uuid.uuid4(), name="Studio Quality", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Projet Qualité Audit", source_lang="fr", target_lang="fr", status="draft")
        db.add(project); db.commit(); db.refresh(project)
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="test_quality.mp4", status="confirmed")
        db.add(media); db.commit(); db.refresh(media)
        # Créer 4 répliques avec des scores de confiance variés pour tester les zones à faible confiance
        r1 = Replica(id=uuid.uuid4(), media_id=media.id, text="Bonjour le monde", start_ms=0, end_ms=2000, order_index=0, typo_codes={}, confidence_score=0.95)
        r2 = Replica(id=uuid.uuid4(), media_id=media.id, text="Texte incertain", start_ms=2000, end_ms=4000, order_index=1, typo_codes={}, confidence_score=0.45)  # faible
        r3 = Replica(id=uuid.uuid4(), media_id=media.id, text="Moyen", start_ms=4000, end_ms=6000, order_index=2, typo_codes={}, confidence_score=0.75)  # moyen
        r4 = Replica(id=uuid.uuid4(), media_id=media.id, text="Parfait", start_ms=6000, end_ms=8000, order_index=3, typo_codes={"italique": True}, confidence_score=0.92)
        db.add_all([r1, r2, r3, r4]); db.commit()
        return studio, project, media, [r1, r2, r3, r4]
    finally:
        db.close()

def _wait_for_export(export_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/v1/exports/{export_id}")
        assert resp.status_code == 200
        status = resp.json()["status"]
        if status == "completed":
            return resp.json()
        if status == "failed":
            raise AssertionError(f"Export failed: {resp.json()}")
        time.sleep(0.2)
    raise AssertionError(f"Export {export_id} not completed within {timeout}s")

def test_export_quality_report_generation_and_metrics():
    """Condition d'achèvement : génération du journal d'analyse qualité et vérification des métriques clés §12.4"""
    studio, project, media, replicas = _setup_project_with_replicas_for_quality()
    try:
        # POST avec format quality_report (alias principal)
        resp = client.post(f"/api/v1/projects/{project.id}/exports", json={"format": "quality_report"})
        assert resp.status_code == 202, f"POST quality_report failed: {resp.status_code} {resp.text}"
        data = resp.json()
        export_id = data["id"]
        assert data["format"] == "quality_report"
        assert data["status"] in ("pending", "processing", "completed")

        result = _wait_for_export(export_id)
        assert result["format"] == "quality_report"
        assert result["status"] == "completed"

        # Download et vérification PDF bien formé
        resp_dl = client.get(f"/api/v1/exports/{export_id}/download")
        assert resp_dl.status_code == 200
        assert resp_dl.headers["content-type"] == "application/pdf"
        content = resp_dl.content
        assert content.startswith(b"%PDF"), f"PDF should start with %PDF, got {content[:20]}"
        assert len(content) > 1000, f"Quality report PDF too small: {len(content)}"

        # Vérification des métriques clés attendues §12.4
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(content))
        text = ""
        for page in reader.pages:
            try:
                text += page.extract_text() or ""
            except:
                pass
        # Le test vérifie la présence des métriques clés
        # On est tolérant sur la casse et les accents
        text_lower = text.lower()
        # Journal d'analyse / Rapport de synthèse
        assert "journal d'analyse" in text_lower or "journal d'analyse qualité" in text_lower, f"PDF should contain 'Journal d'analyse qualité', got {text[:1000]}"
        assert "rapport pdf de synthèse" in text_lower or "rapport" in text_lower, f"PDF should contain 'Rapport PDF de synthèse', got {text[:500]}"
        # Scores de confiance
        assert "score de confiance" in text_lower, f"PDF should contain 'Score de confiance', got {text[:1000]}"
        assert "confiance moyenne" in text_lower or "confiance agrégé" in text_lower, f"PDF should contain moyenne/agrégé, got {text[:1000]}"
        # Zones à faible confiance
        assert "zones à faible confiance" in text_lower or "faible confiance" in text_lower, f"PDF should contain 'Zones à faible confiance', got {text[:1000]}"
        # Audit qualité
        assert "audit qualité" in text_lower or "audit" in text_lower, f"PDF should contain 'audit qualité', got {text[:1000]}"
        # Vérifier que les scores des répliques sont présents
        # On a créé des répliques avec 0.95, 0.45, 0.75, 0.92
        assert "0.950" in text or "0.95" in text, f"PDF should contain confidence 0.95"
        assert "0.450" in text or "0.45" in text, f"PDF should contain low confidence 0.45"
        # Vérifier le nombre de répliques
        assert "4" in text and "répliques" in text_lower, f"PDF should mention 4 répliques"

        # Nettoyage
        db = TestingSessionLocal()
        db.query(Export).filter(Export.id == uuid.UUID(export_id)).delete()
        db.commit()
        _clean_db(db)
        db.query(Export).delete()
        db.commit()
        db.close()
    finally:
        db = TestingSessionLocal()
        try:
            db.query(Export).delete()
            _clean_db(db)
            db.commit()
        except:
            pass
        db.close()

def test_export_quality_report_aliases():
    """Vérifie que les alias de format qualité sont acceptés"""
    studio, project, media, replicas = _setup_project_with_replicas_for_quality()
    try:
        for fmt in ["quality", "quality_report", "qreport", "quality_pdf"]:
            resp = client.post(f"/api/v1/projects/{project.id}/exports", json={"format": fmt})
            assert resp.status_code == 202, f"Format {fmt} should be accepted, got {resp.status_code} {resp.text}"
            export_id = resp.json()["id"]
            result = _wait_for_export(export_id)
            assert result["status"] == "completed"
            resp_dl = client.get(f"/api/v1/exports/{export_id}/download")
            assert resp_dl.status_code == 200
            assert resp_dl.content.startswith(b"%PDF")
            # Cleanup
            db = TestingSessionLocal()
            db.query(Export).filter(Export.id == uuid.UUID(export_id)).delete()
            db.commit()
            db.close()

        db = TestingSessionLocal()
        _clean_db(db)
        db.query(Export).delete()
        db.commit()
        db.close()
    finally:
        db = TestingSessionLocal()
        try:
            db.query(Export).delete()
            _clean_db(db)
            db.commit()
        except:
            pass
        db.close()

def test_export_quality_report_empty_project():
    """Un projet sans répliques doit quand même générer un rapport valide"""
    db = TestingSessionLocal()
    try:
        _clean_db(db)
        db.query(Export).delete()
        db.commit()
        studio = Studio(id=uuid.uuid4(), name="Studio Empty Quality", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Empty Quality Project", source_lang="fr", target_lang="fr", status="draft")
        db.add(project); db.commit(); db.refresh(project)
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="empty_quality.mp4", status="confirmed")
        db.add(media); db.commit()
        db.close()

        resp = client.post(f"/api/v1/projects/{project.id}/exports", json={"format": "quality_report"})
        assert resp.status_code == 202
        export_id = resp.json()["id"]
        result = _wait_for_export(export_id)
        assert result["status"] == "completed"
        resp_dl = client.get(f"/api/v1/exports/{export_id}/download")
        assert resp_dl.status_code == 200
        assert resp_dl.content.startswith(b"%PDF")
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(resp_dl.content))
        text = "".join([p.extract_text() or "" for p in reader.pages])
        assert "0" in text and "répliques" in text.lower()

        db = TestingSessionLocal()
        db.query(Export).filter(Export.id == uuid.UUID(export_id)).delete()
        db.commit()
        _clean_db(db)
        db.query(Export).delete()
        db.commit()
        db.close()
    finally:
        db = TestingSessionLocal()
        try:
            db.query(Export).delete()
            _clean_db(db)
            db.commit()
        except:
            pass
        db.close()
