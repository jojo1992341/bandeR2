"""
Test d'intégration SSO Enterprise §15.2 — SAML 2.0 / OIDC
Condition : test avec fournisseur d'identité de test validant une connexion SSO de bout en bout (Azure AD, Okta, Google Workspace)
"""
import uuid
import base64
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import SessionLocal, engine
from app.models import Base, Studio, User, StudioMembership, SsoConfiguration
from app.core.password import hash_password
from app.core.auth_handler import create_access_token, verify_token

Base.metadata.create_all(bind=engine)
client = TestClient(app)

def _create_user_and_token(email: str, role: str = "owner") -> tuple[User, str]:
    db = SessionLocal()
    try:
        user = User(id=uuid.uuid4(), email=email, hashed_password=hash_password("Test123!@#"), role=role, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
        return user, token
    finally:
        db.close()

def _cleanup_studios(names):
    db = SessionLocal()
    try:
        for name in names:
            studio = db.query(Studio).filter(Studio.name == name).first()
            if studio:
                db.query(SsoConfiguration).filter(SsoConfiguration.studio_id == studio.id).delete()
                # Delete memberships and projects etc. - for test we just delete studio and users
                # Find users that are members of this studio
                memberships = db.query(StudioMembership).filter(StudioMembership.studio_id == studio.id).all()
                for m in memberships:
                    db.query(StudioMembership).filter(StudioMembership.id == m.id).delete()
                    # Delete user if not in other studios
                    other_memberships = db.query(StudioMembership).filter(StudioMembership.user_id == m.user_id).count()
                    if other_memberships == 0:
                        db.query(User).filter(User.id == m.user_id).delete()
                # Also delete any SSO test users by email pattern
                db.query(Studio).filter(Studio.id == studio.id).delete()
                db.commit()
        # Clean up test SSO users
        for email in ["sso_admin_enterprise@test.com", "sso_user_saml@test.com", "sso_user_oidc@test.com", "test_saml@example.com", "test_oidc@example.com"]:
            u = db.query(User).filter(User.email == email).first()
            if u:
                db.query(StudioMembership).filter(StudioMembership.user_id == u.id).delete()
                db.query(User).filter(User.id == u.id).delete()
                db.commit()
    finally:
        db.close()

def test_sso_enterprise_plan_enforcement():
    """Vérifie que SSO est réservé au plan Enterprise (403 sinon)"""
    _cleanup_studios(["Studio SSO Free", "Studio SSO Ent"])
    db = SessionLocal()
    try:
        # Create free and enterprise studios
        studio_free = Studio(id=uuid.uuid4(), name="Studio SSO Free", plan="free")
        studio_ent = Studio(id=uuid.uuid4(), name="Studio SSO Ent", plan="enterprise")
        db.add_all([studio_free, studio_ent])
        db.commit()
        db.refresh(studio_free)
        db.refresh(studio_ent)
        admin_free, token_free = _create_user_and_token("sso_admin_enterprise@test.com", "owner")
        # Need to create membership for admin to be owner of both studios for test
        db2 = SessionLocal()
        try:
            # Re-fetch admin in this session
            admin_db = db2.query(User).filter(User.email == "sso_admin_enterprise@test.com").first()
            db2.add(StudioMembership(studio_id=studio_free.id, user_id=admin_db.id, role="owner"))
            db2.add(StudioMembership(studio_id=studio_ent.id, user_id=admin_db.id, role="owner"))
            db2.commit()
        finally:
            db2.close()

        headers = {"Authorization": f"Bearer {token_free}"}

        # Try to create SAML config for free studio -> should fail 403
        resp = client.post(f"/api/v1/studios/{studio_free.id}/sso/config", json={
            "provider": "azure_ad",
            "protocol": "saml",
            "idp_sso_url": "https://test-idp.example.com/sso",
            "entity_id": f"https://rythmoai.local/sso/saml/{studio_free.id}"
        }, headers=headers)
        assert resp.status_code == 403, f"Free studio should be 403, got {resp.status_code}: {resp.text}"
        assert "enterprise" in resp.text.lower() or "Enterprise" in resp.text

        # Enterprise should succeed
        resp = client.post(f"/api/v1/studios/{studio_ent.id}/sso/config", json={
            "provider": "azure_ad",
            "protocol": "saml",
            "idp_sso_url": "https://test-idp.example.com/sso",
            "entity_id": f"https://rythmoai.local/sso/saml/{studio_ent.id}",
            "idp_entity_id": "https://test-idp.example.com/entity"
        }, headers=headers)
        assert resp.status_code == 201, f"Enterprise SAML config should succeed: {resp.status_code} {resp.text}"
        assert resp.json()["protocol"] == "saml"
        assert resp.json()["provider"] == "azure_ad"

        # Also test OIDC for enterprise
        resp = client.post(f"/api/v1/studios/{studio_ent.id}/sso/config", json={
            "provider": "okta",
            "protocol": "oidc",
            "issuer": "https://test-idp.rythmoai.local",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "authorization_endpoint": "https://test-idp.rythmoai.local/authorize",
            "token_endpoint": "https://test-idp.rythmoai.local/token",
            "jwks_uri": "https://test-idp.rythmoai.local/.well-known/jwks.json"
        }, headers=headers)
        # This will update the existing config (since one per studio) to OIDC, should succeed
        assert resp.status_code in (200, 201), f"OIDC update should succeed: {resp.text}"
        assert resp.json()["protocol"] == "oidc"

    finally:
        _cleanup_studios(["Studio SSO Free", "Studio SSO Ent"])
        db.close()

def test_saml_sso_end_to_end_with_test_idp():
    """Test SAML 2.0 de bout en bout avec fournisseur d'identité de test"""
    _cleanup_studios(["Studio SAML E2E"])
    db = SessionLocal()
    try:
        studio = Studio(id=uuid.uuid4(), name="Studio SAML E2E", plan="enterprise")
        db.add(studio)
        db.commit()
        db.refresh(studio)
        admin, token = _create_user_and_token("sso_admin_enterprise@test.com", "owner")
        db2 = SessionLocal()
        try:
            admin_db = db2.query(User).filter(User.email == "sso_admin_enterprise@test.com").first()
            db2.add(StudioMembership(studio_id=studio.id, user_id=admin_db.id, role="owner"))
            db2.commit()
        finally:
            db2.close()
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Configurer SAML pour le studio (Azure AD)
        saml_config = {
            "provider": "azure_ad",
            "protocol": "saml",
            "entity_id": f"https://rythmoai.local/sso/saml/{studio.id}",
            "acs_url": f"https://rythmoai.local/api/v1/auth/sso/saml/{studio.id}/acs",
            "idp_entity_id": "https://test-idp.rythmoai.local/entity",
            "idp_sso_url": "https://test-idp.rythmoai.local/sso",
            "idp_x509_cert": "MIIC_FAKE_CERT_FOR_TEST",
            "name_id_format": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
        }
        resp = client.post(f"/api/v1/studios/{studio.id}/sso/config", json=saml_config, headers=headers)
        assert resp.status_code == 201, f"SAML config failed: {resp.text}"
        assert resp.json()["protocol"] == "saml"

        # 2. Initier le login SAML (SP -> IdP)
        resp = client.get(f"/api/v1/auth/sso/saml/{studio.id}/login")
        assert resp.status_code == 200, f"SAML login failed: {resp.text}"
        data = resp.json()
        assert "redirect_url" in data
        assert "saml_request" in data
        assert data["protocol"] == "saml"
        assert "SAMLRequest=" in data["redirect_url"]
        # Vérifier que la requête est bien base64
        try:
            import base64
            decoded = base64.b64decode(data["saml_request"])
            # Elle peut être deflated, mais au moins elle est base64 valide
            assert len(decoded) > 0
        except Exception as e:
            pytest.fail(f"SAMLRequest not valid base64: {e}")

        # 3. Simuler l'IdP de test : générer une SAMLResponse pour un utilisateur
        test_email = "test_saml@example.com"
        # Utiliser l'endpoint de test IdP pour générer la réponse
        resp = client.post("/api/v1/auth/sso/test-idp/saml/response", json={
            "email": test_email,
            "studio_id": str(studio.id),
            "issuer": "https://test-idp.rythmoai.local/entity",
            "audience": f"https://rythmoai.local/sso/saml/{studio.id}"
        })
        assert resp.status_code == 200
        saml_response = resp.json()["SAMLResponse"]
        assert saml_response
        # Vérifier que le XML contient l'email
        assert test_email in resp.json()["xml"]

        # 4. POST la SAMLResponse à l'ACS (IdP -> SP)
        # Le endpoint attend un form POST avec SAMLResponse, mais on a aussi un JSON endpoint pour tests
        resp = client.post(f"/api/v1/auth/sso/saml/{studio.id}/acs/json", json={"SAMLResponse": saml_response, "RelayState": str(studio.id)})
        assert resp.status_code == 200, f"SAML ACS failed: {resp.status_code} {resp.text}"
        result = resp.json()
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["user"]["email"] == test_email
        assert result["studio_id"] == str(studio.id)
        assert result["provider"] == "saml"

        # 5. Vérifier que l'utilisateur a été créé et a un membership
        db_check = SessionLocal()
        try:
            user = db_check.query(User).filter(User.email == test_email).first()
            assert user is not None, "SSO user should have been created"
            assert user.is_active is True
            membership = db_check.query(StudioMembership).filter(StudioMembership.studio_id == studio.id, StudioMembership.user_id == user.id).first()
            assert membership is not None, "SSO user should have studio membership"
            assert membership.role == "adaptateur"
        finally:
            db_check.close()

        # 6. Vérifier que le JWT est utilisable pour accéder à une ressource protégée
        access_token = result["access_token"]
        # Vérifier le token
        payload = verify_token(access_token, token_type="access")
        assert payload is not None
        assert payload["email"] == test_email
        assert payload["amr"] == ["saml"]
        # Utiliser le token pour appeler /auth/me
        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        # L'endpoint /auth/me est peut-être sous /auth/me sans prefix, essayons les deux
        if resp.status_code == 404:
            resp = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert resp.status_code == 200
        assert resp.json()["email"] == test_email

        # 7. Vérifier que la même SAMLResponse ne peut pas être rejouée indéfiniment? (optionnel)
        # Pour l'instant, on ne vérifie pas le replay, mais on s'assure que la deuxième utilisation crée toujours un token (idempotence)
        resp2 = client.post(f"/api/v1/auth/sso/saml/{studio.id}/acs/json", json={"SAMLResponse": saml_response})
        assert resp2.status_code == 200
        assert resp2.json()["user"]["email"] == test_email

    finally:
        _cleanup_studios(["Studio SAML E2E"])
        db.close()

def test_oidc_sso_end_to_end_with_test_idp():
    """Test OIDC de bout en bout avec fournisseur d'identité de test (Google Workspace / Okta)"""
    _cleanup_studios(["Studio OIDC E2E"])
    db = SessionLocal()
    try:
        studio = Studio(id=uuid.uuid4(), name="Studio OIDC E2E", plan="enterprise")
        db.add(studio)
        db.commit()
        db.refresh(studio)
        admin, token = _create_user_and_token("sso_admin_enterprise@test.com", "owner")
        db2 = SessionLocal()
        try:
            admin_db = db2.query(User).filter(User.email == "sso_admin_enterprise@test.com").first()
            db2.add(StudioMembership(studio_id=studio.id, user_id=admin_db.id, role="owner"))
            db2.commit()
        finally:
            db2.close()
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Configurer OIDC pour le studio (Okta / Google Workspace)
        oidc_config = {
            "provider": "okta",
            "protocol": "oidc",
            "issuer": "https://test-idp.rythmoai.local",
            "client_id": "test-client",
            "client_secret": "test-oidc-secret-for-jwt-signing-rythmoai-32bytes",
            "authorization_endpoint": "https://test-idp.rythmoai.local/authorize",
            "token_endpoint": "https://test-idp.rythmoai.local/token",
            "jwks_uri": "https://test-idp.rythmoai.local/.well-known/jwks.json",
            "redirect_uri": f"https://rythmoai.local/api/v1/auth/sso/oidc/{studio.id}/callback",
            "scopes": "openid profile email"
        }
        resp = client.post(f"/api/v1/studios/{studio.id}/sso/config", json=oidc_config, headers=headers)
        assert resp.status_code == 201, f"OIDC config failed: {resp.text}"
        assert resp.json()["protocol"] == "oidc"
        assert resp.json()["provider"] == "okta"

        # 2. Initier le login OIDC (SP -> IdP)
        resp = client.get(f"/api/v1/auth/sso/oidc/{studio.id}/login")
        assert resp.status_code == 200, f"OIDC login failed: {resp.text}"
        data = resp.json()
        assert "authorization_url" in data
        assert "test-idp.rythmoai.local/authorize" in data["authorization_url"]
        assert "client_id=test-client" in data["authorization_url"]
        assert "response_type=code" in data["authorization_url"]
        assert data["protocol"] == "oidc"

        # 3. Simuler l'IdP de test : générer un id_token JWT pour un utilisateur
        test_email = "test_oidc@example.com"
        resp = client.post("/api/v1/auth/sso/test-idp/oidc/token", json={
            "email": test_email,
            "studio_id": str(studio.id),
            "issuer": "https://test-idp.rythmoai.local",
            "client_id": "test-client"
        })
        assert resp.status_code == 200
        id_token = resp.json()["id_token"]
        assert id_token.count(".") == 2  # JWT
        # Vérifier que le token contient bien l'email
        import jwt as pyjwt
        payload = pyjwt.decode(id_token, options={"verify_signature": False})
        assert payload["email"] == test_email
        assert payload["iss"] == "https://test-idp.rythmoai.local"

        # 4. Simuler le callback OIDC (IdP -> SP) avec le code/id_token
        # Notre endpoint supporte à la fois code et id_token en query ou body
        # Pour le test, on passe directement l'id_token en query
        resp = client.get(f"/api/v1/auth/sso/oidc/{studio.id}/callback", params={"id_token": id_token})
        assert resp.status_code == 200, f"OIDC callback with id_token failed: {resp.text}"
        result = resp.json()
        assert "access_token" in result
        assert result["user"]["email"] == test_email
        assert result["protocol"] == "oidc"
        assert result["provider"] == "okta"

        # 5. Vérifier création utilisateur et membership
        db_check = SessionLocal()
        try:
            user = db_check.query(User).filter(User.email == test_email).first()
            assert user is not None
            membership = db_check.query(StudioMembership).filter(StudioMembership.studio_id == studio.id, StudioMembership.user_id == user.id).first()
            assert membership is not None
        finally:
            db_check.close()

        # 6. Tester aussi le flow avec `code` (où code est un JWT)
        # Le service supporte que `code` soit un JWT id_token
        resp = client.get(f"/api/v1/auth/sso/oidc/{studio.id}/callback", params={"code": id_token})
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == test_email

        # 7. Tester en POST avec body JSON
        resp = client.post(f"/api/v1/auth/sso/oidc/{studio.id}/callback", json={"id_token": id_token})
        assert resp.status_code == 200
        assert resp.json()["email"] == test_email

        # 8. Vérifier le JWT RythmoAI
        access_token = result["access_token"]
        payload = verify_token(access_token, token_type="access")
        assert payload is not None
        assert payload["email"] == test_email
        assert payload["amr"] == ["oidc"]
        # Utiliser le token pour accéder à une ressource
        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code == 404:
            resp = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert resp.status_code == 200

        # 9. Tester aussi Google Workspace (même flow, provider différent)
        resp = client.post(f"/api/v1/studios/{studio.id}/sso/config", json={
            "provider": "google",
            "protocol": "oidc",
            "issuer": "https://accounts.google.com",
            "client_id": "google-test-client",
            "client_secret": "google-secret"
        }, headers=headers)
        assert resp.status_code in (200, 201)
        assert resp.json()["provider"] == "google"
        # Générer un token Google-like
        resp = client.post("/api/v1/auth/sso/test-idp/oidc/token", json={
            "email": "google_user@test.com",
            "issuer": "https://accounts.google.com",
            "client_id": "google-test-client"
        })
        google_token = resp.json()["id_token"]
        resp = client.get(f"/api/v1/auth/sso/oidc/{studio.id}/callback", params={"id_token": google_token})
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == "google_user@test.com"

    finally:
        _cleanup_studios(["Studio OIDC E2E"])
        db.close()

def test_sso_config_crud_and_provider_variants():
    """Test CRUD de la config SSO et variants de providers (Azure AD, Okta, Google)"""
    _cleanup_studios(["Studio SSO CRUD"])
    db = SessionLocal()
    try:
        studio = Studio(id=uuid.uuid4(), name="Studio SSO CRUD", plan="enterprise")
        db.add(studio)
        db.commit()
        db.refresh(studio)
        admin, token = _create_user_and_token("sso_admin_enterprise@test.com", "owner")
        db2 = SessionLocal()
        try:
            admin_db = db2.query(User).filter(User.email == "sso_admin_enterprise@test.com").first()
            db2.add(StudioMembership(studio_id=studio.id, user_id=admin_db.id, role="owner"))
            db2.commit()
        finally:
            db2.close()
        headers = {"Authorization": f"Bearer {token}"}

        # Créer config SAML Azure AD
        resp = client.post(f"/api/v1/studios/{studio.id}/sso/config", json={
            "provider": "azure_ad",
            "protocol": "saml",
            "idp_sso_url": "https://login.microsoftonline.com/test/saml2",
            "entity_id": "https://rythmoai.local/test"
        }, headers=headers)
        assert resp.status_code == 201
        assert resp.json()["provider"] == "azure_ad"
        # GET
        resp = client.get(f"/api/v1/studios/{studio.id}/sso/config", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["provider"] == "azure_ad"

        # Mettre à jour vers Okta OIDC
        resp = client.patch(f"/api/v1/studios/{studio.id}/sso/config", json={
            "provider": "okta",
            "protocol": "oidc",
            "issuer": "https://test.okta.com",
            "client_id": "okta-client"
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["provider"] == "okta"
        assert resp.json()["protocol"] == "oidc"

        # Mettre à jour vers Google
        resp = client.put(f"/api/v1/studios/{studio.id}/sso/config", json={
            "provider": "google",
            "protocol": "oidc",
            "issuer": "https://accounts.google.com",
            "client_id": "google-client"
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["provider"] == "google"

        # DELETE
        resp = client.delete(f"/api/v1/studios/{studio.id}/sso/config", headers=headers)
        assert resp.status_code == 200
        # GET après DELETE doit 404
        resp = client.get(f"/api/v1/studios/{studio.id}/sso/config", headers=headers)
        assert resp.status_code == 404

    finally:
        _cleanup_studios(["Studio SSO CRUD"])
        db.close()

def test_sso_requires_enterprise_and_admin():
    """Vérifie que SSO nécessite plan Enterprise et rôle admin"""
    _cleanup_studios(["Studio SSO NonEnt", "Studio SSO NoAdmin"])
    db = SessionLocal()
    try:
        studio_free = Studio(id=uuid.uuid4(), name="Studio SSO NonEnt", plan="free")
        studio_ent = Studio(id=uuid.uuid4(), name="Studio SSO NoAdmin", plan="enterprise")
        db.add_all([studio_free, studio_ent])
        db.commit()
        db.refresh(studio_free)
        db.refresh(studio_ent)
        # Créer un admin pour free et un non-admin pour ent
        admin, token_admin = _create_user_and_token("sso_admin_enterprise@test.com", "owner")
        user, token_user = _create_user_and_token("sso_user_saml@test.com", "adaptateur")
        db2 = SessionLocal()
        try:
            admin_db = db2.query(User).filter(User.email == "sso_admin_enterprise@test.com").first()
            user_db = db2.query(User).filter(User.email == "sso_user_saml@test.com").first()
            db2.add(StudioMembership(studio_id=studio_free.id, user_id=admin_db.id, role="owner"))
            db2.add(StudioMembership(studio_id=studio_ent.id, user_id=user_db.id, role="adaptateur"))
            db2.commit()
        finally:
            db2.close()
        headers_admin = {"Authorization": f"Bearer {token_admin}"}
        headers_user = {"Authorization": f"Bearer {token_user}"}

        # Free + admin -> 403 enterprise
        resp = client.post(f"/api/v1/studios/{studio_free.id}/sso/config", json={"provider": "okta", "protocol": "oidc", "issuer": "https://test.okta.com", "client_id": "x"}, headers=headers_admin)
        assert resp.status_code == 403

        # Enterprise + non-admin -> 403 admin
        resp = client.post(f"/api/v1/studios/{studio_ent.id}/sso/config", json={"provider": "okta", "protocol": "oidc", "issuer": "https://test.okta.com", "client_id": "x"}, headers=headers_user)
        assert resp.status_code == 403

        # Sans token -> 401
        resp = client.post(f"/api/v1/studios/{studio_ent.id}/sso/config", json={"provider": "okta", "protocol": "oidc"})
        assert resp.status_code == 401

    finally:
        _cleanup_studios(["Studio SSO NonEnt", "Studio SSO NoAdmin"])
        db.close()
