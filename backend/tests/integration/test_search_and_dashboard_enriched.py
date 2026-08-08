"""
Test d'intégration §16.1 — Recherche full-text + Dashboard enrichi (US-053)
- Recherche dans les transcriptions de l'ensemble des projets d'un studio (PostgreSQL full-text search avec fallback SQLite LIKE)
- Dashboard enrichi : stats d'usage/performance par projet
Condition d'achèvement : recherche textuelle retourne les projets et répliques pertinents en dessous d'un seuil de latence acceptable.
"""
import uuid
import time
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import engine, SessionLocal as TestingSessionLocal
from app.models import Base, Studio, Project, MediaAsset, TranscriptSegment, Word, Replica, Speaker, PipelineJob, Export

Base.metadata.create_all(bind=engine)
client = TestClient(app)

def _setup_studio_with_searchable_content():
    """
    Crée un studio avec 3 projets, chacun avec des transcriptions et répliques contenant des termes distincts
    pour tester la recherche full-text.
    """
    db = TestingSessionLocal()
    try:
        # Nettoyage
        db.query(Word).delete()
        db.query(TranscriptSegment).delete()
        db.query(Replica).delete()
        db.query(Speaker).delete()
        db.query(MediaAsset).delete()
        db.query(PipelineJob).delete()
        db.query(Project).delete()
        db.query(Studio).delete()
        try:
            db.query(Export).delete()
        except:
            pass
        db.commit()

        studio = Studio(id=uuid.uuid4(), name="Studio Search Enrichi", plan="pro", quotas={"ai_minutes_limit": 600, "ai_minutes_used": 120})
        db.add(studio)
        db.commit()
        db.refresh(studio)

        # Projet 1 : contient "banane" et "rythmo"
        p1 = Project(id=uuid.uuid4(), studio_id=studio.id, title="Projet Banane", source_lang="fr", target_lang="fr", status="En_edition")
        # Projet 2 : contient "pomme" et "doublage"
        p2 = Project(id=uuid.uuid4(), studio_id=studio.id, title="Projet Pomme", source_lang="fr", target_lang="fr", status="Valide")
        # Projet 3 : contient "banane" aussi mais avec orthographe différente (bananes)
        p3 = Project(id=uuid.uuid4(), studio_id=studio.id, title="Projet Bananes Pomme", source_lang="fr", target_lang="fr", status="Archive")
        db.add_all([p1, p2, p3])
        db.commit()
        db.refresh(p1); db.refresh(p2); db.refresh(p3)

        # Pour chaque projet, créer un media + speakers + transcripts + replicas + words
        projects = [p1, p2, p3]
        # Textes distincts
        texts = [
            ["Bonjour la banane et le rythmo défilant", "La bande rythmo est géniale avec des bananes"],
            ["La pomme et le doublage du film", "Le comédien double la pomme verte"],
            ["Mélange bananes pommes et rythmo", "Un autre texte avec banane et pomme"]
        ]
        for idx, proj in enumerate(projects):
            media = MediaAsset(id=uuid.uuid4(), project_id=proj.id, storage_path=f"search_media_{idx}.mp4", status="confirmed", duration_seconds=120.0, file_size_bytes=50*1024*1024)
            db.add(media)
            db.flush()
            # Speaker
            spk = Speaker(id=uuid.uuid4(), project_id=proj.id, label=f"Speaker {idx}", color="#e11d48")
            db.add(spk)
            db.flush()
            # Transcript segments
            for seg_idx, txt in enumerate(texts[idx]):
                seg = TranscriptSegment(id=uuid.uuid4(), media_id=media.id, text=txt, start_ms=seg_idx*2000, end_ms=(seg_idx+1)*2000, language="fr", confidence_score=0.9)
                db.add(seg)
                db.flush()
                # Words
                for w_idx, word in enumerate(txt.split()):
                    w = Word(id=uuid.uuid4(), segment_id=seg.id, text=word, start_ms=seg.start_ms + w_idx*100, end_ms=seg.start_ms + (w_idx+1)*100, language="fr", confidence_score=0.9, speaker_id=spk.id if w_idx % 2 == 0 else None)
                    db.add(w)
                # Replicas (correspondent aux segments)
                rep = Replica(id=uuid.uuid4(), media_id=media.id, speaker_id=spk.id, text=txt, start_ms=seg.start_ms, end_ms=seg.end_ms, order_index=seg_idx, typo_codes={"crochets": True} if "rythmo" in txt else {}, confidence_score=0.9)
                db.add(rep)
            # Pipeline job pour stats
            job = PipelineJob(id=uuid.uuid4(), project_id=proj.id, status="completed", progress_percent=100, current_step="export", updated_at=datetime.now(timezone.utc) - timedelta(hours=idx))
            db.add(job)
        db.commit()
        return {"studio_id": studio.id, "project_ids": [str(p.id) for p in projects]}
    finally:
        db.close()

def _cleanup():
    db = TestingSessionLocal()
    try:
        db.query(Word).delete()
        db.query(TranscriptSegment).delete()
        db.query(Replica).delete()
        db.query(Speaker).delete()
        db.query(MediaAsset).delete()
        db.query(PipelineJob).delete()
        db.query(Project).delete()
        db.query(Studio).delete()
        try:
            db.query(Export).delete()
        except:
            pass
        db.commit()
    finally:
        db.close()

class TestFullTextSearch:
    def test_search_returns_relevant_projects_and_replicas(self):
        fixture = _setup_studio_with_searchable_content()
        studio_id = fixture["studio_id"]
        try:
            # Recherche "banane" — doit retourner P1 et P3 (et leurs répliques), pas P2 (pomme)
            start = time.time()
            resp = client.get(f"/api/v1/studios/{studio_id}/search?q=banane&limit=20")
            latency_ms = int((time.time() - start) * 1000)
            assert resp.status_code == 200, f"Search failed: {resp.text}"
            data = resp.json()
            # Vérifier latence acceptable (<500ms pour petit dataset, seuil test 1000ms)
            assert data["latency_ms"] < 1000, f"Latence trop élevée: {data['latency_ms']}ms"
            assert latency_ms < 1000, f"Latence mesurée trop élevée: {latency_ms}ms"
            # Vérifier que les projets pertinents sont retournés
            assert data["total_projects"] >= 2, f"Recherche banane doit retourner au moins 2 projets, got {data['total_projects']}"
            project_titles = [p["title"] for p in data["projects"]]
            assert "Projet Banane" in project_titles or any("Banane" in t for t in project_titles), f"Projet Banane manquant: {project_titles}"
            # Vérifier répliques
            assert data["total_replicas"] >= 2, f"Doit avoir au moins 2 répliques pour banane"
            for rep in data["replicas"]:
                assert "banan" in rep["text"].lower(), f"Réplique non pertinente: {rep['text']}"
                assert "<mark>" in rep["highlighted"], f"Highlight manquant: {rep['highlighted']}"

            # Recherche "pomme" — doit retourner P2 et P3
            resp2 = client.get(f"/api/v1/studios/{studio_id}/search?q=pomme&limit=20")
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert data2["total_projects"] >= 2
            assert any("pomme" in r["text"].lower() for r in data2["replicas"])

            # Recherche "rythmo" — P1 et P3
            resp3 = client.get(f"/api/v1/studios/{studio_id}/search?q=rythmo&limit=20")
            assert resp3.status_code == 200
            data3 = resp3.json()
            assert data3["total_projects"] >= 2
            assert data3["total_replicas"] >= 2

            # Recherche insensible à la casse et accents
            resp4 = client.get(f"/api/v1/studios/{studio_id}/search?q=BANANE&limit=20")
            assert resp4.status_code == 200
            assert resp4.json()["total_projects"] >= 2

            # Recherche avec pagination
            resp5 = client.get(f"/api/v1/studios/{studio_id}/search?q=banane&limit=1&offset=0")
            assert resp5.status_code == 200
            assert len(resp5.json()["replicas"]) <= 1

            # Recherche vide ou trop courte (<2) doit retourner 0 ou erreur 422
            resp6 = client.get(f"/api/v1/studios/{studio_id}/search?q=a&limit=20")
            # Soit 422 (validation), soit 200 avec 0 résultats
            assert resp6.status_code in (200, 422)
            if resp6.status_code == 200:
                assert resp6.json()["total_projects"] == 0 or resp6.json()["query"] == "a"

            # Recherche sur studio inexistant -> 404
            fake = uuid.uuid4()
            resp7 = client.get(f"/api/v1/studios/{fake}/search?q=banane")
            assert resp7.status_code == 404

        finally:
            _cleanup()

    def test_search_isolation_between_studios(self):
        """Vérifie l'isolation multi-tenant : la recherche ne retourne que les projets du studio demandé."""
        # Créer 2 studios
        db = TestingSessionLocal()
        try:
            db.query(Word).delete()
            db.query(TranscriptSegment).delete()
            db.query(Replica).delete()
            db.query(Speaker).delete()
            db.query(MediaAsset).delete()
            db.query(PipelineJob).delete()
            db.query(Project).delete()
            db.query(Studio).delete()
            db.commit()
            s1 = Studio(id=uuid.uuid4(), name="Studio A Search", plan="pro")
            s2 = Studio(id=uuid.uuid4(), name="Studio B Search", plan="pro")
            db.add_all([s1, s2]); db.commit(); db.refresh(s1); db.refresh(s2)
            p1 = Project(id=uuid.uuid4(), studio_id=s1.id, title="Projet A Secret", source_lang="fr", target_lang="fr", status="draft")
            p2 = Project(id=uuid.uuid4(), studio_id=s2.id, title="Projet B Secret", source_lang="fr", target_lang="fr", status="draft")
            db.add_all([p1, p2]); db.commit(); db.refresh(p1); db.refresh(p2)
            for proj, txt in [(p1, "contenu secret studio A banane"), (p2, "contenu secret studio B pomme")]:
                m = MediaAsset(id=uuid.uuid4(), project_id=proj.id, storage_path=f"iso_{proj.id}.mp4", status="confirmed")
                db.add(m); db.flush()
                seg = TranscriptSegment(id=uuid.uuid4(), media_id=m.id, text=txt, start_ms=0, end_ms=2000, language="fr", confidence_score=0.9)
                db.add(seg); db.flush()
                r = Replica(id=uuid.uuid4(), media_id=m.id, text=txt, start_ms=0, end_ms=2000, order_index=0, typo_codes={}, confidence_score=0.9)
                db.add(r)
            db.commit()
            studio_a_id = str(s1.id)
            studio_b_id = str(s2.id)
        finally:
            db.close()

        try:
            resp_a = client.get(f"/api/v1/studios/{studio_a_id}/search?q=banane")
            assert resp_a.status_code == 200
            # Ne doit trouver que le projet A
            assert resp_a.json()["total_projects"] >= 1
            for proj in resp_a.json()["projects"]:
                assert proj["id"] != studio_b_id
                assert "secret" in proj["title"].lower() or "A" in proj["title"]

            resp_b = client.get(f"/api/v1/studios/{studio_b_id}/search?q=pomme")
            assert resp_b.status_code == 200
            assert resp_b.json()["total_projects"] >= 1

            # Recherche "secret" sur studio A ne doit pas retourner le projet B
            resp_a_secret = client.get(f"/api/v1/studios/{studio_a_id}/search?q=secret")
            assert resp_a_secret.status_code == 200
            # Vérifier que seul le studio A est retourné
            for proj in resp_a_secret.json()["projects"]:
                assert proj["title"] != "Projet B Secret"

        finally:
            _cleanup()

    def test_search_latency_under_threshold(self):
        """Vérifie que la recherche reste sous le seuil de latence acceptable même avec un peu de volume."""
        fixture = _setup_studio_with_searchable_content()
        studio_id = fixture["studio_id"]
        try:
            # Ajouter plus de données pour tester la latence : 50 répliques supplémentaires avec du texte aléatoire
            db = TestingSessionLocal()
            try:
                proj = db.query(Project).filter(Project.studio_id == studio_id).first()
                media = db.query(MediaAsset).filter(MediaAsset.project_id == proj.id).first()
                # Ajouter 50 répliques avec texte "lorem ipsum"
                for i in range(50):
                    r = Replica(id=uuid.uuid4(), media_id=media.id, text=f"lorem ipsum test {i} avec banane", start_ms=i*1000, end_ms=(i+1)*1000, order_index=10+i, typo_codes={}, confidence_score=0.8)
                    db.add(r)
                db.commit()
            finally:
                db.close()

            # Mesurer la latence
            start = time.time()
            resp = client.get(f"/api/v1/studios/{studio_id}/search?q=banane&limit=50")
            elapsed_ms = int((time.time() - start) * 1000)
            assert resp.status_code == 200
            data = resp.json()
            # Seuil acceptable : < 500ms pour ce volume (en SQLite, sans GIN, doit rester rapide)
            # Pour PostgreSQL avec GIN, ce serait < 100ms
            assert data["latency_ms"] < 500, f"Latence {data['latency_ms']}ms dépasse le seuil 500ms (elapsed {elapsed_ms}ms)"
            assert elapsed_ms < 500, f"Latence mesurée {elapsed_ms}ms dépasse le seuil"

            # Vérifier le moteur utilisé est documenté
            assert data["engine"] in ("postgres", "sqlite", "meilisearch"), f"Moteur inattendu: {data['engine']}"

            # Tester suggest endpoint rapide
            start2 = time.time()
            resp2 = client.get(f"/api/v1/studios/{studio_id}/search/suggest?q=ban&limit=5")
            elapsed2_ms = int((time.time() - start2) * 1000)
            assert resp2.status_code == 200
            assert resp2.json()["latency_ms"] < 500
            assert elapsed2_ms < 500

        finally:
            _cleanup()

class TestDashboardEnriched:
    def test_dashboard_per_project_stats(self):
        fixture = _setup_studio_with_searchable_content()
        studio_id = fixture["studio_id"]
        try:
            resp = client.get(f"/api/v1/studios/{studio_id}/dashboard")
            assert resp.status_code == 200
            data = resp.json()
            # Vérifier que chaque projet a des stats enrichies
            for proj in data["projects"]:
                assert "stats" in proj, f"Projet {proj['title']} doit avoir stats enrichies"
                stats = proj["stats"]
                # Champs attendus US-053
                assert "replica_count" in stats
                assert "speaker_count" in stats
                assert "transcript_segment_count" in stats
                assert "word_count" in stats
                assert "avg_confidence" in stats
                assert "total_duration_seconds" in stats
                assert "storage_mb" in stats
                assert "pipeline_duration_seconds" in stats or stats["pipeline_duration_seconds"] is None
                # Vérifier que les valeurs sont cohérentes
                assert stats["replica_count"] >= 1, f"Projet {proj['title']} doit avoir au moins 1 réplique"
                assert stats["word_count"] >= 1

            # Vérifier les indicateurs enrichis
            ind = data["indicators"]
            assert "total_replicas" in ind, "Indicateur total_replicas manquant"
            assert "total_speakers" in ind, "Indicateur total_speakers manquant"
            assert "total_duration_seconds" in ind
            assert "total_storage_mb" in ind
            assert "total_words" in ind
            assert "total_transcripts" in ind
            assert "avg_confidence_global" in ind
            assert "top_projects" in ind
            # Valeurs
            assert ind["total_replicas"] >= 6, f"Total replicas doit être >=6, got {ind['total_replicas']}"
            assert ind["total_speakers"] >= 3
            assert ind["total_duration_seconds"] > 0
            assert ind["total_words"] > 0

            # Vérifier que les anciens indicateurs sont toujours présents (non régression)
            assert "total_projects" in ind
            assert "status_distribution" in ind
            assert "volume_month" in ind
            assert "quota" in ind
            assert "avg_processing_seconds" in ind

        finally:
            _cleanup()

    def test_dashboard_performance_with_many_projects(self):
        """Vérifie que le dashboard reste performant avec un peu de volume."""
        fixture = _setup_studio_with_searchable_content()
        studio_id = fixture["studio_id"]
        try:
            # Ajouter 20 projets supplémentaires avec des stats minimales
            db = TestingSessionLocal()
            try:
                studio = db.query(Studio).filter(Studio.id == studio_id).first()
                for i in range(20):
                    p = Project(id=uuid.uuid4(), studio_id=studio.id, title=f"Projet Perf {i}", source_lang="fr", target_lang="fr", status="En_edition")
                    db.add(p)
                    db.flush()
                    m = MediaAsset(id=uuid.uuid4(), project_id=p.id, storage_path=f"perf_{i}.mp4", status="confirmed", duration_seconds=60, file_size_bytes=10*1024*1024)
                    db.add(m)
                    db.flush()
                    r = Replica(id=uuid.uuid4(), media_id=m.id, text=f"Test perf {i}", start_ms=0, end_ms=1000, order_index=0, typo_codes={}, confidence_score=0.85)
                    db.add(r)
                db.commit()
            finally:
                db.close()

            start = time.time()
            resp = client.get(f"/api/v1/studios/{studio_id}/dashboard")
            elapsed_ms = int((time.time() - start) * 1000)
            assert resp.status_code == 200
            data = resp.json()
            # Seuil de latence pour le dashboard enrichi : < 1000ms même avec 23 projets
            assert elapsed_ms < 1000, f"Dashboard trop lent: {elapsed_ms}ms"
            assert len(data["projects"]) >= 20
            assert data["indicators"]["total_projects"] >= 20
        finally:
            _cleanup()
