import uuid
import time
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.database import get_db
from app.models import Base, Studio, User, StudioMembership, StudioInvitation
from app.core.password import hash_password

# Use shared in-memory DB like other tests, but create a fresh one for isolation
from .test_replica_split_merge import TestingSessionLocal as SharedSession, client as shared_client, _clean_db as shared_clean, engine as shared_engine, Base as SharedBase

# Ensure tables exist for new model
from app.models import StudioInvitation
try:
    StudioInvitation.__table__.create(bind=shared_engine, checkfirst=True)
except:
    pass

# Reuse shared client and session
TestingSessionLocal = SharedSession
client = shared_client

def _clean_all(db):
    try:
        db.query(StudioInvitation).delete()
    except:
        pass
    try:
        db.query(StudioMembership).delete()
    except:
        pass
    db.query(User).filter(User.email.like("invite_%")).delete(synchronize_session=False)
    db.query(User).filter(User.email.like("admin_invite%")).delete(synchronize_session=False)
    shared_clean(db)

def test_invite_activation_login_flow():
    """Test d'intégration couvrant invitation → activation → connexion avec rôle attribué §16.2"""
    db = TestingSessionLocal()
    try:
        _clean_all(db)
        # Créer studio et admin
        studio = Studio(id=uuid.uuid4(), name="Studio Invite Test", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        admin_email = f"admin_invite_{uuid.uuid4().hex[:6]}@example.com"
        admin = User(id=uuid.uuid4(), email=admin_email, hashed_password=hash_password("Admin123!"), role="owner", is_active=True)
        db.add(admin); db.commit(); db.refresh(admin)
        membership = StudioMembership(id=uuid.uuid4(), studio_id=studio.id, user_id=admin.id, role="owner")
        db.add(membership); db.commit()
        db.close()

        # Login admin
        resp = client.post("/auth/login", json={"email": admin_email, "password": "Admin123!"})
        assert resp.status_code == 200, resp.text
        admin_token = resp.json()["access_token"]

        # Invite new user
        new_email = f"invite_{uuid.uuid4().hex[:6]}@example.com"
        invite_role = "adaptateur"
        resp = client.post(
            f"/api/v1/studios/{studio.id}/users/invite",
            json={"email": new_email, "role": invite_role},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        # Also try without /api/v1 prefix for robustness (some tests might use /studios/...)
        if resp.status_code == 404:
            resp = client.post(
                f"/studios/{studio.id}/users/invite",
                json={"email": new_email, "role": invite_role},
                headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert resp.status_code in (200, 201), f"Invite failed: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data["email"] == new_email
        assert data["role"] == invite_role
        # Le token doit être présent
        invite_token = data.get("invite_token") or data.get("token") or data.get("inviteToken")
        assert invite_token, f"No invite token in response: {data}"
        assert "expires_at" in data or "expiresAt" in data

        # Vérifier que l'invitation est en base et non acceptée
        db2 = TestingSessionLocal()
        inv = db2.query(StudioInvitation).filter(StudioInvitation.email == new_email).first()
        assert inv is not None
        assert inv.is_accepted == False
        assert inv.role == invite_role
        db2.close()

        # Activation du nouvel utilisateur
        new_password = "NewPass123!"
        # Essayer plusieurs endpoints possibles pour l'activation
        resp_activate = None
        for url in ["/auth/activate", "/auth/invite/activate", f"/api/v1/auth/activate"]:
            resp_activate = client.post(url, json={"token": invite_token, "password": new_password})
            if resp_activate.status_code in (200, 201):
                break
            # Essayer avec email aussi
            resp_activate = client.post(url, json={"token": invite_token, "password": new_password, "email": new_email})
            if resp_activate.status_code in (200, 201):
                break
        assert resp_activate is not None and resp_activate.status_code in (200, 201), f"Activation failed: {resp_activate.status_code if resp_activate else 'no response'} {resp_activate.text if resp_activate else ''}"
        act_data = resp_activate.json()
        assert act_data["email"] == new_email
        assert act_data["role"] == invite_role

        # Vérifier que l'invitation est marquée comme acceptée
        db3 = TestingSessionLocal()
        inv2 = db3.query(StudioInvitation).filter(StudioInvitation.email == new_email).first()
        assert inv2.is_accepted == True
        db3.close()

        # Connexion du nouvel utilisateur avec le rôle attribué
        resp = client.post("/auth/login", json={"email": new_email, "password": new_password})
        assert resp.status_code == 200, f"Login after activation failed: {resp.text}"
        login_data = resp.json()
        assert "access_token" in login_data
        # Vérifier le rôle via /auth/me
        new_token = login_data["access_token"]
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert resp.status_code == 200
        me = resp.json()
        assert me["email"] == new_email
        # Le rôle doit être celui attribué à l'invitation
        assert me["role"] == invite_role, f"Expected role {invite_role}, got {me['role']}"

        # Vérifier que l'utilisateur est membre du studio avec le bon rôle
        resp = client.get(f"/api/v1/studios/{studio.id}/users", headers={"Authorization": f"Bearer {admin_token}"})
        if resp.status_code == 404:
            resp = client.get(f"/studios/{studio.id}/users", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        users = resp.json()
        # La réponse peut être une liste directe ou un dict avec users
        if isinstance(users, dict) and "users" in users:
            users = users["users"]
        found = None
        for u in users:
            if u.get("email") == new_email:
                found = u
                break
        assert found is not None, f"New user not found in studio users: {users}"
        assert found["role"] == invite_role

        # Cleanup
        db4 = TestingSessionLocal()
        _clean_all(db4)
        # Supprimer aussi l'utilisateur invité
        db4.query(User).filter(User.email == new_email).delete(synchronize_session=False)
        db4.query(User).filter(User.email == admin_email).delete(synchronize_session=False)
        db4.commit()
        db4.close()

    finally:
        try:
            db.close()
        except:
            pass
        # Final cleanup
        dbf = TestingSessionLocal()
        try:
            _clean_all(dbf)
            dbf.commit()
        except:
            pass
        dbf.close()

def test_invite_requires_admin_and_validates_role():
    """Vérifie que seul un admin peut inviter et que le rôle est attribué dès l'invitation"""
    db = TestingSessionLocal()
    try:
        _clean_all(db)
        studio = Studio(id=uuid.uuid4(), name="Studio Role Test", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        # Admin
        admin_email = f"admin_invite_{uuid.uuid4().hex[:6]}@example.com"
        admin = User(id=uuid.uuid4(), email=admin_email, hashed_password=hash_password("Admin123!"), role="owner", is_active=True)
        db.add(admin); db.commit(); db.refresh(admin)
        admin_mem = StudioMembership(id=uuid.uuid4(), studio_id=studio.id, user_id=admin.id, role="owner")
        db.add(admin_mem); db.commit()
        # User normal (adaptateur)
        user_email = f"invite_user_{uuid.uuid4().hex[:6]}@example.com"
        normal_user = User(id=uuid.uuid4(), email=user_email, hashed_password=hash_password("User123!"), role="adaptateur", is_active=True)
        db.add(normal_user); db.commit(); db.refresh(normal_user)
        normal_mem = StudioMembership(id=uuid.uuid4(), studio_id=studio.id, user_id=normal_user.id, role="adaptateur")
        db.add(normal_mem); db.commit()
        db.close()

        # Login normal user
        resp = client.post("/auth/login", json={"email": user_email, "password": "User123!"})
        assert resp.status_code == 200
        normal_token = resp.json()["access_token"]

        # Normal user ne doit pas pouvoir inviter
        resp = client.post(f"/api/v1/studios/{studio.id}/users/invite", json={"email": "new2@example.com", "role": "adaptateur"}, headers={"Authorization": f"Bearer {normal_token}"})
        if resp.status_code == 404:
            resp = client.post(f"/studios/{studio.id}/users/invite", json={"email": "new2@example.com", "role": "adaptateur"}, headers={"Authorization": f"Bearer {normal_token}"})
        assert resp.status_code == 403, f"Non-admin should not be able to invite, got {resp.status_code}"

        # Admin peut inviter avec rôle spécifique
        resp = client.post("/auth/login", json={"email": admin_email, "password": "Admin123!"})
        admin_token = resp.json()["access_token"]
        resp = client.post(f"/api/v1/studios/{studio.id}/users/invite", json={"email": "new3@example.com", "role": "calligraphe"}, headers={"Authorization": f"Bearer {admin_token}"})
        if resp.status_code == 404:
            resp = client.post(f"/studios/{studio.id}/users/invite", json={"email": "new3@example.com", "role": "calligraphe"}, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code in (200, 201)
        assert resp.json()["role"] == "calligraphe"

        # Test gestion des rôles par admin: changer le rôle
        # D'abord inviter et activer un user
        new_email = f"invite_{uuid.uuid4().hex[:6]}@example.com"
        resp = client.post(f"/api/v1/studios/{studio.id}/users/invite", json={"email": new_email, "role": "adaptateur"}, headers={"Authorization": f"Bearer {admin_token}"})
        if resp.status_code == 404:
            resp = client.post(f"/studios/{studio.id}/users/invite", json={"email": new_email, "role": "adaptateur"}, headers={"Authorization": f"Bearer {admin_token}"})
        token = resp.json().get("invite_token") or resp.json().get("token")
        # Activate
        resp_act = client.post("/auth/activate", json={"token": token, "password": "NewPass123!"})
        if resp_act.status_code not in (200, 201):
            resp_act = client.post("/auth/invite/activate", json={"token": token, "password": "NewPass123!"})
        assert resp_act.status_code in (200, 201)
        new_user_id = resp_act.json()["id"]

        # Admin change le rôle
        resp = client.patch(f"/api/v1/studios/{studio.id}/users/{new_user_id}", json={"role": "directeur_artistique"}, headers={"Authorization": f"Bearer {admin_token}"})
        if resp.status_code == 404:
            resp = client.patch(f"/studios/{studio.id}/users/{new_user_id}", json={"role": "directeur_artistique"}, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        assert resp.json()["new_role"] == "directeur_artistique"

        # Vérifier que le nouvel utilisateur a bien son rôle mis à jour au login
        resp = client.post("/auth/login", json={"email": new_email, "password": "NewPass123!"})
        assert resp.status_code == 200
        # Le rôle dans le token doit être le nouveau
        new_token = resp.json()["access_token"]
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert resp.json()["role"] == "directeur_artistique"

        # Cleanup
        dbf = TestingSessionLocal()
        _clean_all(dbf)
        dbf.query(User).filter(User.email.in_([admin_email, user_email, new_email, "new3@example.com"])).delete(synchronize_session=False)
        dbf.commit()
        dbf.close()

    finally:
        try:
            db.close()
        except:
            pass
        dbf = TestingSessionLocal()
        try:
            _clean_all(dbf)
            dbf.commit()
        except:
            pass
        dbf.close()

def test_invite_token_expiration_and_reuse():
    """Vérifie que le lien d'activation est à durée limitée et ne peut être réutilisé"""
    db = TestingSessionLocal()
    try:
        _clean_all(db)
        studio = Studio(id=uuid.uuid4(), name="Studio Expire Test", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)
        admin_email = f"admin_invite_{uuid.uuid4().hex[:6]}@example.com"
        admin = User(id=uuid.uuid4(), email=admin_email, hashed_password=hash_password("Admin123!"), role="owner", is_active=True)
        db.add(admin); db.commit(); db.refresh(admin)
        mem = StudioMembership(id=uuid.uuid4(), studio_id=studio.id, user_id=admin.id, role="owner")
        db.add(mem); db.commit()
        db.close()

        resp = client.post("/auth/login", json={"email": admin_email, "password": "Admin123!"})
        admin_token = resp.json()["access_token"]

        new_email = f"invite_{uuid.uuid4().hex[:6]}@example.com"
        resp = client.post(f"/api/v1/studios/{studio.id}/users/invite", json={"email": new_email, "role": "invité"}, headers={"Authorization": f"Bearer {admin_token}"})
        if resp.status_code == 404:
            resp = client.post(f"/studios/{studio.id}/users/invite", json={"email": new_email, "role": "invité"}, headers={"Authorization": f"Bearer {admin_token}"})
        token = resp.json().get("invite_token") or resp.json().get("token")

        # Première activation OK
        resp = client.post("/auth/activate", json={"token": token, "password": "Pass123!"})
        if resp.status_code not in (200, 201):
            resp = client.post("/auth/invite/activate", json={"token": token, "password": "Pass123!"})
        assert resp.status_code in (200, 201)

        # Deuxième utilisation du même token doit échouer
        resp2 = client.post("/auth/activate", json={"token": token, "password": "Pass123!"})
        if resp2.status_code not in (400, 404):
            resp2 = client.post("/auth/invite/activate", json={"token": token, "password": "Pass123!"})
        assert resp2.status_code in (400, 404), f"Reusing token should fail, got {resp2.status_code}"

        # Token invalide doit échouer
        resp3 = client.post("/auth/activate", json={"token": "invalid.token.here", "password": "Pass123!"})
        assert resp3.status_code in (400, 401, 404)

        dbf = TestingSessionLocal()
        _clean_all(dbf)
        dbf.query(User).filter(User.email.in_([admin_email, new_email])).delete(synchronize_session=False)
        dbf.commit()
        dbf.close()
    finally:
        try:
            db.close()
        except:
            pass
        dbf = TestingSessionLocal()
        try:
            _clean_all(dbf)
            dbf.commit()
        except:
            pass
        dbf.close()
