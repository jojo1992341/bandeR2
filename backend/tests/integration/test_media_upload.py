import uuid
import tempfile
import os
import boto3
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from app.core.auth_handler import create_access_token
from app.core.password import hash_password
from app.models import User, Project, Studio, StudioMembership

client = TestClient(app)

def get_db():
    return SessionLocal()

def setup_users(db: Session):
    studio = Studio(id=uuid.uuid4(), name="Media Studio", plan="pro")
    db.add(studio)
    db.commit()
    user = User(id=uuid.uuid4(), email="media@test.com", hashed_password=hash_password("test"), role="adaptateur", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(studio)
    membership = StudioMembership(id=uuid.uuid4(), studio_id=studio.id, user_id=user.id, role="adaptateur")
    db.add(membership)
    db.commit()
    project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Media Test", source_lang="fr", target_lang="fr", status="draft")
    db.add(project)
    db.commit()
    db.refresh(project)
    return user, project

def test_media_upload_flow():
    db = get_db()
    project = None
    user = None
    studio = None
    try:
        user, project = setup_users(db)
        token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})

        # 1. Upload URL (pas de file bytes dans la requête API)
        resp = client.post(
            f"/projects/{project.id}/media/upload-url",
            json={"filename": "test.mp4", "content_type": "video/mp4"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 201, f"upload-url échoué: {resp.text}"
        data = resp.json()
        assert "upload_url" in data
        assert "media_id" in data
        assert "key" in data
        assert data["expires_in"] == 600

        # 2. Upload direct vers S3 (pas de transit par FastAPI)
        # Utiliser boto3 directement
        import boto3
        s3 = boto3.client("s3", endpoint_url="http://localhost:9000", aws_access_key_id="minioadmin", aws_secret_access_key="minioadmin")
        # Créer un fichier vidéo valide temporaire avec ffmpeg
        tmp_valid = "/tmp/test_valid.mp4"
        os.system(f"ffmpeg -f lavfi -i testsrc=duration=1:size=320x240:rate=1 -pix_fmt yuv420p {tmp_valid} -y 2>/dev/null")
        s3.upload_file(tmp_valid, "rythmoai-media", data["key"])

        # 3. Confirm avec validation ffprobe
        resp = client.post(
            f"/media/{data['media_id']}/confirm",
            json={"key": data["key"]},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200, f"confirm échoué: {resp.text}"
        confirm = resp.json()
        assert confirm["status"] == "confirmed"
        assert confirm["format_detected"] is not None

        # 4. Upload fichier corrompu (mauvais format / pas un flux vidéo) → US-004
        tmp_bad = "/tmp/test_bad.mp4"
        with open(tmp_bad, "w") as f:
            f.write("Ceci n'est pas un fichier vidéo")
        s3.upload_file(tmp_bad, "rythmoai-media", f"projects/{project.id}/media/{uuid.uuid4()}/bad.mp4")

        # Créer une entrée media pour le mauvais fichier
        bad_media = None  # on utilisera un nouveau media via upload-url
        # Pour simplifier : on réutilise le même endpoint avec un autre media
        resp_bad = client.post(
            f"/projects/{project.id}/media/upload-url",
            json={"filename": "bad.mp4", "content_type": "video/mp4"},
            headers={"Authorization": f"Bearer {token}"}
        )
        bad_data = resp_bad.json()
        s3.upload_file(tmp_bad, "rythmoai-media", bad_data["key"])

        resp_confirm_bad = client.post(
            f"/media/{bad_data['media_id']}/confirm",
            json={"key": bad_data["key"]},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp_confirm_bad.status_code == 422, f"Rejet attendu US-004, reçu {resp_confirm_bad.status_code}"
        detail = resp_confirm_bad.json()["detail"]
        assert "non supporté" in detail or "US-004" in detail or "attendus" in detail, f"Message explicite manquant: {detail}"

        # Nettoyage S3
        try:
            s3.delete_object(Bucket="rythmoai-media", Key=data["key"])
            s3.delete_object(Bucket="rythmoai-media", Key=bad_data["key"])
        except Exception:
            pass
    finally:
        if project is not None:
            db.query(Project).filter(Project.id == project.id).delete(synchronize_session=False)
        if user is not None:
            db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        if studio is not None:
            db.query(Studio).filter(Studio.id == studio.id).delete(synchronize_session=False)
        db.commit()
        db.close()
