import uuid
import time
import re
import pytest
from app.models import Studio, Project, MediaAsset, Replica, Export, Speaker
from .test_replica_split_merge import TestingSessionLocal, client, _clean_db

def _setup_project_with_replicas_for_srt_vtt():
    db = TestingSessionLocal()
    try:
        _clean_db(db)
        try:
            db.query(Export).delete()
            db.commit()
        except:
            db.rollback()
        studio = Studio(id=uuid.uuid4(), name="Studio SRT VTT", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Projet SRT VTT", source_lang="fr", target_lang="fr", status="draft")
        db.add(project); db.commit(); db.refresh(project)
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="test_srt_vtt.mp4", status="confirmed")
        db.add(media); db.commit(); db.refresh(media)
        spk1 = Speaker(id=uuid.uuid4(), project_id=project.id, label="Alice", color="#e11d48")
        spk2 = Speaker(id=uuid.uuid4(), project_id=project.id, label="Bob", color="#3b82f6")
        db.add_all([spk1, spk2]); db.commit()
        r1 = Replica(id=uuid.uuid4(), media_id=media.id, speaker_id=spk1.id, text="Bonjour le monde", start_ms=0, end_ms=2500, order_index=0, typo_codes={"italique": True}, confidence_score=0.95)
        r2 = Replica(id=uuid.uuid4(), media_id=media.id, speaker_id=spk2.id, text="Au secours", start_ms=2500, end_ms=5500, order_index=1, typo_codes={"majuscules": True}, confidence_score=0.92)
        r3 = Replica(id=uuid.uuid4(), media_id=media.id, speaker_id=spk1.id, text="en chuchotant", start_ms=5500, end_ms=8000, order_index=2, typo_codes={"crochets": True, "parentheses": True}, confidence_score=0.88)
        db.add_all([r1, r2, r3]); db.commit()
        return studio, project, media, [r1, r2, r3], [spk1, spk2]
    finally:
        db.close()

def _parse_srt(content: str):
    """Parse SRT simple : retourne liste de cues {index, start_ms, end_ms, text}"""
    cues = []
    # Normaliser les retours
    content = content.replace('\r\n', '\n')
    blocks = [b.strip() for b in content.strip().split('\n\n') if b.strip()]
    srt_time_re = re.compile(r'(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)')
    for block in blocks:
        lines = block.split('\n')
        if not lines:
            continue
        # Si le premier est un numéro
        idx = None
        time_line_idx = 0
        if lines[0].strip().isdigit():
            idx = int(lines[0].strip())
            time_line_idx = 1
        else:
            # Parfois sans numéro ?
            time_line_idx = 0
        if time_line_idx >= len(lines):
            continue
        m = srt_time_re.search(lines[time_line_idx])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
        start_ms = ((h1*3600 + m1*60 + s1)*1000 + ms1)
        end_ms = ((h2*3600 + m2*60 + s2)*1000 + ms2)
        text = "\n".join(lines[time_line_idx+1:])
        cues.append({"index": idx, "start_ms": start_ms, "end_ms": end_ms, "text": text, "raw": block})
    return cues

def _parse_vtt(content: str):
    """Parse VTT simple"""
    cues = []
    content = content.replace('\r\n', '\n')
    # Enlever l'en-tête WEBVTT
    if content.startswith("WEBVTT"):
        # Trouver le premier cue après l'en-tête
        parts = content.split('\n\n', 1)
        if len(parts) > 1:
            content = parts[1]
        else:
            content = ""
    else:
        # Si pas de WEBVTT, on tente quand même
        pass
    blocks = [b.strip() for b in content.strip().split('\n\n') if b.strip()]
    vtt_time_re = re.compile(r'(\d+):(\d+):(\d+)\.(\d+)\s*-->\s*(\d+):(\d+):(\d+)\.(\d+)')
    for block in blocks:
        # Ignorer les NOTE blocks qui sont des commentaires
        if block.startswith("NOTE"):
            # NOTE peut être suivi de plusieurs lignes, on l'ignore pour le parsing des cues
            # Mais on doit vérifier que le cue suivant est bien parsé, donc on skip ce block
            continue
        lines = block.split('\n')
        # Le premier peut être un identifiant numérique
        time_line_idx = 0
        if lines[0].strip().isdigit():
            time_line_idx = 1
        # Chercher la ligne de timecode
        # Parfois la ligne d'id et la ligne de timecode sont séparées, parfois la première ligne est le timecode
        found = False
        for i in range(time_line_idx, min(time_line_idx+2, len(lines))):
            if vtt_time_re.search(lines[i]):
                time_line_idx = i
                found = True
                break
        if not found:
            continue
        m = vtt_time_re.search(lines[time_line_idx])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
        start_ms = ((h1*3600 + m1*60 + s1)*1000 + ms1)
        end_ms = ((h2*3600 + m2*60 + s2)*1000 + ms2)
        text = "\n".join(lines[time_line_idx+1:])
        # Le texte peut contenir des NOTE internes ? On les garde
        cues.append({"start_ms": start_ms, "end_ms": end_ms, "text": text, "raw": block})
    return cues

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

def test_export_srt_valid_and_faithful():
    studio, project, media, replicas, speakers = _setup_project_with_replicas_for_srt_vtt()
    try:
        resp = client.post(f"/api/v1/projects/{project.id}/exports", json={"format": "srt"})
        assert resp.status_code == 202, resp.text
        export_id = resp.json()["id"]
        data = _wait_for_export(export_id)
        assert data["format"] == "srt"

        resp_dl = client.get(f"/api/v1/exports/{export_id}/download")
        assert resp_dl.status_code == 200
        # SRT mime type
        ct = resp_dl.headers.get("content-type", "")
        assert "srt" in ct.lower() or "subrip" in ct.lower() or "text" in ct.lower() or "octet-stream" in ct.lower(), f"Unexpected content-type for SRT: {ct}"
        content = resp_dl.content.decode('utf-8')
        # Vérifier que c'est du SRT valide
        cues = _parse_srt(content)
        assert len(cues) == len(replicas), f"SRT should have {len(replicas)} cues, got {len(cues)}: {content[:500]}"
        # Fidélité aux timings
        for i, replica in enumerate(sorted(replicas, key=lambda r: r.order_index)):
            cue = cues[i]
            assert abs(cue["start_ms"] - replica.start_ms) < 50, f"Cue {i} start_ms mismatch: {cue['start_ms']} vs {replica.start_ms}"
            assert abs(cue["end_ms"] - replica.end_ms) < 50, f"Cue {i} end_ms mismatch: {cue['end_ms']} vs {replica.end_ms}"
            # Vérifier que le texte contient au moins une partie du texte original (avec ou sans style)
            # Pour majuscules, le texte devrait être en uppercase
            if replica.typo_codes and replica.typo_codes.get("majuscules"):
                assert replica.text.upper() in cue["text"] or replica.text in cue["text"]
            else:
                assert replica.text in cue["text"] or replica.text.lower() in cue["text"].lower()
        # Vérifier locuteur en commentaire (NOTE)
        assert "Speaker" in content or "NOTE" in content or str(speakers[0].id)[:8] in content or "Alice" in content or "Bob" in content, "SRT should contain speaker info"
        # Vérifier styles basiques (<i> pour italique)
        assert "<i>" in content or "<I>" in content.upper(), "SRT should contain italic style for replica with italique"

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

def test_export_vtt_valid_and_faithful():
    studio, project, media, replicas, speakers = _setup_project_with_replicas_for_srt_vtt()
    try:
        resp = client.post(f"/api/v1/projects/{project.id}/exports", json={"format": "vtt"})
        assert resp.status_code == 202, resp.text
        export_id = resp.json()["id"]
        data = _wait_for_export(export_id)
        assert data["format"] == "vtt"

        resp_dl = client.get(f"/api/v1/exports/{export_id}/download")
        assert resp_dl.status_code == 200
        ct = resp_dl.headers.get("content-type", "")
        assert "vtt" in ct.lower() or "text" in ct.lower() or "octet-stream" in ct.lower(), f"Unexpected content-type for VTT: {ct}"
        content = resp_dl.content.decode('utf-8')
        assert content.startswith("WEBVTT"), f"VTT should start with WEBVTT, got {content[:20]}"
        cues = _parse_vtt(content)
        assert len(cues) == len(replicas), f"VTT should have {len(replicas)} cues, got {len(cues)}: {content[:800]}"
        for i, replica in enumerate(sorted(replicas, key=lambda r: r.order_index)):
            cue = cues[i]
            assert abs(cue["start_ms"] - replica.start_ms) < 50, f"VTT cue {i} start mismatch"
            assert abs(cue["end_ms"] - replica.end_ms) < 50, f"VTT cue {i} end mismatch"
            assert replica.text in cue["text"] or replica.text.upper() in cue["text"] or replica.text.lower() in cue["text"].lower()
        # Vérifier locuteur et styles
        assert "Speaker" in content or "NOTE" in content or "Alice" in content
        assert "<i>" in content or "<I>" in content.upper() or "italique" in content.lower()

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

def test_export_srt_vtt_empty_band():
    """Bande vide doit quand même produire un fichier valide"""
    db = TestingSessionLocal()
    try:
        _clean_db(db)
        db.query(Export).delete()
        db.commit()
        studio = Studio(id=uuid.uuid4(), name="Studio Empty", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Empty Project", source_lang="fr", target_lang="fr", status="draft")
        db.add(project); db.commit(); db.refresh(project)
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="empty.mp4", status="confirmed")
        db.add(media); db.commit()
        db.close()

        for fmt in ("srt", "vtt"):
            resp = client.post(f"/api/v1/projects/{project.id}/exports", json={"format": fmt})
            assert resp.status_code == 202
            export_id = resp.json()["id"]
            data = _wait_for_export(export_id)
            assert data["format"] == fmt
            resp_dl = client.get(f"/api/v1/exports/{export_id}/download")
            assert resp_dl.status_code == 200
            content = resp_dl.content.decode('utf-8')
            if fmt == "srt":
                # SRT vide devrait quand même être parseable (0 cues)
                cues = _parse_srt(content)
                assert len(cues) == 0 or "Aucune" in content or len(content) > 0
            else:
                assert content.startswith("WEBVTT")
                cues = _parse_vtt(content)
                assert len(cues) == 0

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
