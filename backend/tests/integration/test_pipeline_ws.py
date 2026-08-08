import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from app.models import Project, Studio, User
from app.core.password import hash_password

client = TestClient(app)

def test_pipeline_ws_and_polling_fallback():
    db = SessionLocal()
    try:
        studio = Studio(id=uuid.uuid4(), name="WS Studio", plan="pro")
        db.add(studio)
        db.commit()
        user = User(id=uuid.uuid4(), email="ws@test.com", hashed_password=hash_password("test"), role="adaptateur", is_active=True)
        db.add(user)
        db.commit()
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="WS Project", source_lang="fr", target_lang="fr", status="draft")
        db.add(project)
        db.commit()
        db.refresh(project)

        # WebSocket : recevoir au moins 3 mises à jour distinctes
        with client.websocket_connect(f"/ws/projects/{project.id}/pipeline") as ws:
            messages = []
            # Message initial
            msg = ws.receive_json()
            assert msg.get("type") == "status"
            messages.append(msg)

            # Déclencher 3 mises à jour progressives
            for _ in range(3):
                ws.send_json({"trigger": "next"})
                msg = ws.receive_json()
                messages.append(msg)
                assert msg.get("type") == "progress"
                assert msg.get("progress_percent") > messages[-2]["progress_percent"] or msg.get("current_step") != messages[-2]["current_step"]

        # Repli REST toutes les 3 secondes (simulé par appel direct)
        resp = client.get(f"/projects/{project.id}/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "progress_percent" in data
        assert "current_step" in data

        # Nettoyage
        db.query(Project).filter(Project.id == project.id).delete(synchronize_session=False)
        db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db.query(Studio).filter(Studio.id == studio.id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
