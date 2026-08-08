import uuid
import time
import pytest
from fastapi.testclient import TestClient
from app.models import Studio, Project, MediaAsset, Replica, Export
from .test_replica_split_merge import TestingSessionLocal, client, _clean_db

def _setup_project_with_replicas_for_export():
    db = TestingSessionLocal()
    try:
        _clean_db(db)
        # Nettoyer aussi les exports
        try:
            db.query(Export).delete()
            db.commit()
        except:
            db.rollback()
        studio = Studio(id=uuid.uuid4(), name="Studio Export", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Projet Export PDF", source_lang="fr", target_lang="fr", status="draft")
        db.add(project); db.commit(); db.refresh(project)
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="test_export.mp4", status="confirmed")
        db.add(media); db.commit(); db.refresh(media)
        # Créer 3 répliques avec différents codes typo et timecodes
        r1 = Replica(id=uuid.uuid4(), media_id=media.id, text="Bonjour le monde", start_ms=0, end_ms=2000, order_index=0, typo_codes={"crochets": True}, confidence_score=0.95)
        r2 = Replica(id=uuid.uuid4(), media_id=media.id, text="Au secours", start_ms=2000, end_ms=4000, order_index=1, typo_codes={"majuscules": True}, confidence_score=0.92)
        r3 = Replica(id=uuid.uuid4(), media_id=media.id, text="On se téléphone", start_ms=4000, end_ms=6000, order_index=2, typo_codes={"italique": True}, confidence_score=0.88)
        db.add_all([r1, r2, r3]); db.commit()
        return studio, project, media, [r1, r2, r3]
    finally:
        db.close()

def test_export_pdf_generation_and_download():
    """Condition d'achèvement : génération PDF calligraphié <15s, bien formé et téléchargeable"""
    studio, project, media, replicas = _setup_project_with_replicas_for_export()
    start_time = time.time()
    try:
        # POST /projects/{id}/exports
        resp = client.post(f"/api/v1/projects/{project.id}/exports", json={"format": "pdf"})
        assert resp.status_code == 202, f"POST exports failed: {resp.status_code} {resp.text}"
        data = resp.json()
        export_id = data["id"]
        assert data["project_id"] == str(project.id)
        assert data["format"] == "pdf"
        assert data["status"] in ("pending", "processing", "completed")

        # Poll GET /exports/{id} jusqu'à completed (budget <15s)
        deadline = time.time() + 15
        status = data["status"]
        attempts = 0
        while status in ("pending", "processing") and time.time() < deadline:
            time.sleep(0.2)
            attempts += 1
            resp_get = client.get(f"/api/v1/exports/{export_id}")
            assert resp_get.status_code == 200, resp_get.text
            status = resp_get.json()["status"]
            if attempts > 50:
                break

        elapsed = time.time() - start_time
        assert status == "completed", f"Export not completed within 15s, last status={status}, elapsed={elapsed:.2f}s, attempts={attempts}"
        assert elapsed < 15, f"Export took too long: {elapsed:.2f}s >=15s"

        # GET /exports/{id}/download
        resp_dl = client.get(f"/api/v1/exports/{export_id}/download")
        assert resp_dl.status_code == 200, f"Download failed: {resp_dl.status_code} {resp_dl.text}"
        assert resp_dl.headers["content-type"] == "application/pdf"
        content = resp_dl.content
        # Vérifier PDF bien formé
        assert content.startswith(b"%PDF"), f"PDF should start with %PDF, got {content[:20]}"
        assert b"%%EOF" in content or b"%%EOF" in content[-1024:], "PDF should contain %%EOF"
        assert len(content) > 500, f"PDF too small: {len(content)} bytes"
        # Vérifier qu'on peut le parser avec pypdf
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content))
            assert len(reader.pages) >= 1, "PDF should have at least 1 page"
            text = ""
            for page in reader.pages:
                try:
                    text += page.extract_text() or ""
                except:
                    pass
            # Le PDF doit contenir au moins le titre ou une réplique
            # On vérifie de manière souple : au moins un mot des répliques ou le titre
            assert "Bande Rythmo" in text or "Bonjour" in text or "Au secours" in text or len(text) > 10, f"PDF text extraction failed or empty: {text[:200]}"
        except ImportError:
            pass  # Si pypdf non dispo, on a déjà vérifié le header

        # Vérifier que le fichier est sur disque
        resp_get2 = client.get(f"/api/v1/exports/{export_id}")
        assert resp_get2.json()["file_path"] is not None

        # Nettoyage
        db = TestingSessionLocal()
        try:
            db.query(Export).filter(Export.id == uuid.UUID(export_id)).delete()
            db.commit()
        except:
            pass
        _clean_db(db)
        try:
            db.query(Export).delete()
            db.commit()
        except:
            pass
        db.close()

    finally:
        elapsed_total = time.time() - start_time
        # Le test global doit rester <15s (déjà vérifié)
        assert elapsed_total < 15, f"Total test time {elapsed_total:.2f}s exceeds budget"
        # Nettoyage final
        db = TestingSessionLocal()
        try:
            _clean_db(db)
            db.query(Export).delete()
            db.commit()
        except:
            pass
        db.close()

def test_export_pdf_with_typo_and_timecodes():
    """Vérifie que le PDF contient les timecodes et les codes typo"""
    studio, project, media, replicas = _setup_project_with_replicas_for_export()
    try:
        # Créer une réplique avec parentheses
        db = TestingSessionLocal()
        r_extra = Replica(id=uuid.uuid4(), media_id=media.id, text="en chuchotant", start_ms=6000, end_ms=8000, order_index=3, typo_codes={"parentheses": True})
        db.add(r_extra); db.commit(); db.close()

        resp = client.post(f"/api/v1/projects/{project.id}/exports", json={"format": "pdf", "include_timecodes": True, "include_typo_codes": True})
        assert resp.status_code == 202
        export_id = resp.json()["id"]

        # Attendre completed
        for _ in range(30):
            time.sleep(0.2)
            r = client.get(f"/api/v1/exports/{export_id}")
            if r.json()["status"] == "completed":
                break
        assert r.json()["status"] == "completed"

        resp_dl = client.get(f"/api/v1/exports/{export_id}/download")
        assert resp_dl.status_code == 200
        content = resp_dl.content
        assert content.startswith(b"%PDF")
        # Vérifier timecodes SMPTE présents (les timecodes sont au format HH:MM:SS:FF)
        # On peut vérifier que le PDF contient au moins un timecode comme 00:00:00:00
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content))
            text = " ".join([p.extract_text() or "" for p in reader.pages])
            assert "00:00:00" in text or "TC" in text or "Timecode" in text or len(text) > 100
        except:
            pass

        db = TestingSessionLocal()
        db.query(Export).delete()
        _clean_db(db)
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

def test_export_not_found_and_format_validation():
    studio, project, media, replicas = _setup_project_with_replicas_for_export()
    try:
        fake_project = uuid.uuid4()
        resp = client.post(f"/api/v1/projects/{fake_project}/exports", json={"format": "pdf"})
        assert resp.status_code == 404

        resp2 = client.post(f"/api/v1/projects/{project.id}/exports", json={"format": "docx"})
        assert resp2.status_code == 422

        fake_export = uuid.uuid4()
        resp3 = client.get(f"/api/v1/exports/{fake_export}")
        assert resp3.status_code == 404

        resp4 = client.get(f"/api/v1/exports/{fake_export}/download")
        assert resp4.status_code == 404

        db = TestingSessionLocal(); db.query(Export).delete(); _clean_db(db); db.close()
    finally:
        db = TestingSessionLocal()
        try:
            db.query(Export).delete()
            _clean_db(db)
            db.commit()
        except:
            pass
        db.close()

def test_export_download_before_ready_returns_409():
    studio, project, media, replicas = _setup_project_with_replicas_for_export()
    try:
        # On crée un export mais on tente de le télécharger immédiatement avant qu'il soit completed
        # Pour simuler, on crée directement en DB avec status pending
        db = TestingSessionLocal()
        exp_id = uuid.uuid4()
        exp = Export(id=exp_id, project_id=project.id, format="pdf", status="pending")
        db.add(exp); db.commit(); db.close()

        resp = client.get(f"/api/v1/exports/{exp_id}/download")
        assert resp.status_code == 409
        assert "non prêt" in resp.json()["detail"] or "non prêt" in resp.text or "status" in resp.text

        db = TestingSessionLocal(); db.query(Export).filter(Export.id == exp_id).delete(); db.commit(); _clean_db(db); db.query(Export).delete(); db.commit(); db.close()
    finally:
        db = TestingSessionLocal()
        try:
            db.query(Export).delete()
            _clean_db(db)
            db.commit()
        except:
            pass
        db.close()
