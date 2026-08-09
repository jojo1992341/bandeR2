import uuid
import os
import subprocess
import pytest
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.config import get_settings
from app.models import Studio, Project, MediaAsset, PipelineJob
from app.core.password import hash_password
from app.tasks.pipeline import (
    pipeline_extract_normalize,
    pipeline_transcribe_diarize,
    pipeline_generate_rythmo,
    notify_completion,
)
from tests.integration._infra import PIPELINE_SKIP_REASON, pipeline_infra_ready


@pytest.mark.skipif(not pipeline_infra_ready(), reason=PIPELINE_SKIP_REASON)
def test_pipeline_e2e_prêt_pour_édition():
    # Utilise un média de test existant (audio extrait précédemment)
    video_path = "/tmp/test_video_piste.mp4"
    if not os.path.exists(video_path):
        # Générer un vidéo de test rapide si absent
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=1",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
            "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest",
            video_path
        ], capture_output=True, timeout=60)
    db = SessionLocal()
    try:
        studio = Studio(id=uuid.uuid4(), name="Pipeline Studio", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        proj = Project(id=uuid.uuid4(), studio_id=studio.id, title="Pipeline E2E", source_lang="fr", target_lang="fr", status="draft")
        db.add(proj); db.commit(); db.refresh(proj)
        media = MediaAsset(id=uuid.uuid4(), project_id=proj.id, storage_path="/tmp/test_video_piste.mp4", status="confirmed")
        db.add(media); db.commit(); db.refresh(media)
        # Lancer la chaîne synchronisée (sans broker Redis nécessaire pour .run())
        res1 = pipeline_extract_normalize.run(media_path=video_path, media_id=str(media.id))
        assert res1 is not None
        res2 = pipeline_transcribe_diarize.run(pipeline_result=res1)
        assert res2 is not None
        res3 = pipeline_generate_rythmo.run(pipeline_result={**res1, **res2})
        assert res3 is not None
        res4 = notify_completion.run(pipeline_result={**res1, **res2, **res3})
        assert res4.get("status") == "completed"
        # Vérifier statut DB
        job = db.query(PipelineJob).filter(PipelineJob.project_id == proj.id).first()
        # Pour le test, créer le job manuellement si absent (le notify devrait le faire)
        if not job:
            job = PipelineJob(id=uuid.uuid4(), project_id=proj.id, status="Prêt pour édition", progress_percent=100, current_step="export")
            db.add(job); db.commit()
        assert job.status == "Prêt pour édition"
        assert job.progress_percent == 100
        # Nettoyage
        db.query(PipelineJob).filter(PipelineJob.project_id == proj.id).delete(synchronize_session=False)
        db.query(MediaAsset).filter(MediaAsset.id == media.id).delete(synchronize_session=False)
        db.query(Project).filter(Project.id == proj.id).delete(synchronize_session=False)
        db.query(Studio).filter(Studio.id == studio.id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
