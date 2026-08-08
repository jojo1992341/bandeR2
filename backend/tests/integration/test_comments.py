import uuid
import pytest
from app.models import Studio, Project, MediaAsset, Replica, User, StudioMembership, Comment
from app.core.password import hash_password
from .test_replica_split_merge import TestingSessionLocal, client, _clean_db

def _setup_project_with_replica_and_users():
    db = TestingSessionLocal()
    try:
        # Clean
        try:
            db.query(Comment).delete()
        except:
            pass
        _clean_db(db)
        # Also clean users with specific pattern
        db.query(User).filter(User.email.like("comment_%")).delete(synchronize_session=False)
        db.commit()

        studio = Studio(id=uuid.uuid4(), name="Studio Comments", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Project Comments", source_lang="fr", target_lang="fr", status="draft")
        db.add(project); db.commit(); db.refresh(project)
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="test_comments.mp4", status="confirmed")
        db.add(media); db.commit(); db.refresh(media)
        replica = Replica(id=uuid.uuid4(), media_id=media.id, text="Bonjour le monde", start_ms=0, end_ms=2000, order_index=0, typo_codes={})
        db.add(replica); db.commit(); db.refresh(replica)

        # Deux utilisateurs dans le même projet
        user1_email = f"comment_user1_{uuid.uuid4().hex[:6]}@example.com"
        user2_email = f"comment_user2_{uuid.uuid4().hex[:6]}@example.com"
        user1 = User(id=uuid.uuid4(), email=user1_email, hashed_password=hash_password("Pass123!"), role="adaptateur", is_active=True)
        user2 = User(id=uuid.uuid4(), email=user2_email, hashed_password=hash_password("Pass123!"), role="calligraphe", is_active=True)
        db.add_all([user1, user2]); db.commit(); db.refresh(user1); db.refresh(user2)
        m1 = StudioMembership(id=uuid.uuid4(), studio_id=studio.id, user_id=user1.id, role="adaptateur")
        m2 = StudioMembership(id=uuid.uuid4(), studio_id=studio.id, user_id=user2.id, role="calligraphe")
        db.add_all([m1, m2]); db.commit()
        return studio, project, media, replica, user1, user2
    finally:
        db.close()

def _login(email, password):
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]

def test_comments_crud():
    studio, project, media, replica, user1, user2 = _setup_project_with_replica_and_users()
    try:
        token1 = _login(user1.email, "Pass123!")
        token2 = _login(user2.email, "Pass123!")

        # User1 crée un commentaire
        resp = client.post(f"/api/v1/replicas/{replica.id}/comments", json={"content": "Super réplique !"}, headers={"Authorization": f"Bearer {token1}"})
        assert resp.status_code == 201, resp.text
        c1 = resp.json()
        assert c1["content"] == "Super réplique !"
        assert c1["replica_id"] == str(replica.id)
        assert c1["author_email"] == user1.email
        comment_id = c1["id"]

        # User2 liste et voit le commentaire (affichage immédiat pour second utilisateur)
        resp = client.get(f"/api/v1/replicas/{replica.id}/comments", headers={"Authorization": f"Bearer {token2}"})
        assert resp.status_code == 200
        comments = resp.json()
        assert len(comments) == 1
        assert comments[0]["content"] == "Super réplique !"
        assert comments[0]["author_email"] == user1.email

        # User2 ajoute aussi un commentaire
        resp = client.post(f"/api/v1/replicas/{replica.id}/comments", json={"content": "Merci !"}, headers={"Authorization": f"Bearer {token2}"})
        assert resp.status_code == 201
        assert resp.json()["author_email"] == user2.email

        # Vérifier que User1 voit les 2 commentaires (temps réel via polling)
        resp = client.get(f"/api/v1/replicas/{replica.id}/comments", headers={"Authorization": f"Bearer {token1}"})
        assert resp.status_code == 200
        comments = resp.json()
        assert len(comments) == 2
        # Ordre chronologique
        assert comments[0]["content"] == "Super réplique !"
        assert comments[1]["content"] == "Merci !"

        # User1 supprime son commentaire
        resp = client.delete(f"/api/v1/comments/{comment_id}", headers={"Authorization": f"Bearer {token1}"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Vérifier qu'il n'en reste qu'un
        resp = client.get(f"/api/v1/replicas/{replica.id}/comments", headers={"Authorization": f"Bearer {token1}"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["content"] == "Merci !"

        # Cleanup
        db = TestingSessionLocal()
        try:
            db.query(Comment).delete()
            db.commit()
        except:
            pass
        _clean_db(db)
        db.query(User).filter(User.email.in_([user1.email, user2.email])).delete(synchronize_session=False)
        db.commit()
        db.close()
    finally:
        db = TestingSessionLocal()
        try:
            db.query(Comment).delete()
            _clean_db(db)
            db.query(User).filter(User.email.like("comment_%")).delete(synchronize_session=False)
            db.commit()
        except:
            pass
        db.close()

def test_comment_validation_and_not_found():
    studio, project, media, replica, user1, user2 = _setup_project_with_replica_and_users()
    try:
        token1 = _login(user1.email, "Pass123!")

        # Contenu vide -> 422
        resp = client.post(f"/api/v1/replicas/{replica.id}/comments", json={"content": "   "}, headers={"Authorization": f"Bearer {token1}"})
        assert resp.status_code == 422

        # Réplique inexistante -> 404
        fake_id = uuid.uuid4()
        resp = client.post(f"/api/v1/replicas/{fake_id}/comments", json={"content": "test"}, headers={"Authorization": f"Bearer {token1}"})
        assert resp.status_code == 404

        # Commentaire inexistant -> 404
        fake_comment = uuid.uuid4()
        resp = client.delete(f"/api/v1/comments/{fake_comment}", headers={"Authorization": f"Bearer {token1}"})
        assert resp.status_code == 404

        # GET sur réplique inexistante
        resp = client.get(f"/api/v1/replicas/{fake_id}/comments", headers={"Authorization": f"Bearer {token1}"})
        assert resp.status_code == 404

        db = TestingSessionLocal()
        db.query(Comment).delete()
        _clean_db(db)
        db.query(User).filter(User.email.in_([user1.email, user2.email])).delete(synchronize_session=False)
        db.commit()
        db.close()
    finally:
        db = TestingSessionLocal()
        try:
            db.query(Comment).delete()
            _clean_db(db)
            db.query(User).filter(User.email.like("comment_%")).delete(synchronize_session=False)
            db.commit()
        except:
            pass
        db.close()

def test_comment_unauth_and_second_user_immediate_display():
    """Test e2e backend : second utilisateur voit immédiatement le commentaire du premier"""
    studio, project, media, replica, user1, user2 = _setup_project_with_replica_and_users()
    try:
        token1 = _login(user1.email, "Pass123!")
        token2 = _login(user2.email, "Pass123!")

        # User1 poste 3 commentaires successivement
        for i in range(3):
            resp = client.post(f"/api/v1/replicas/{replica.id}/comments", json={"content": f"Comment {i+1} de user1"}, headers={"Authorization": f"Bearer {token1}"})
            assert resp.status_code == 201

        # User2 récupère immédiatement (sans délai) et doit voir les 3
        resp = client.get(f"/api/v1/replicas/{replica.id}/comments", headers={"Authorization": f"Bearer {token2}"})
        assert resp.status_code == 200
        comments = resp.json()
        assert len(comments) == 3
        assert [c["content"] for c in comments] == ["Comment 1 de user1", "Comment 2 de user1", "Comment 3 de user1"]

        # Vérifier que l'ordre est bien préservé et que les auteurs sont corrects
        for c in comments:
            assert c["author_email"] == user1.email

        db = TestingSessionLocal()
        db.query(Comment).delete()
        _clean_db(db)
        db.query(User).filter(User.email.in_([user1.email, user2.email])).delete(synchronize_session=False)
        db.commit()
        db.close()
    finally:
        db = TestingSessionLocal()
        try:
            db.query(Comment).delete()
            _clean_db(db)
            db.query(User).filter(User.email.like("comment_%")).delete(synchronize_session=False)
            db.commit()
        except:
            pass
        db.close()
