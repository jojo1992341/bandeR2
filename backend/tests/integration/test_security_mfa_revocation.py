import uuid
import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from app.models import User

client = TestClient(app)


def get_db_session() -> Session:
    return SessionLocal()


def cleanup_users():
    db = get_db_session()
    try:
        db.query(User).filter(
            User.email.in_(
                [
                    "test_admin_mfa@example.com",
                    "user_b_mfa@example.com",
                    "pwned_user@example.com",
                    "safe_user@example.com",
                ]
            )
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_security_mfa_and_session_revocation():
    cleanup_users()
    try:
        # ------------------------------------------------------------------
        # 1. Vérification de la détection de mots de passe compromis (HIBP / offline)
        # ------------------------------------------------------------------
        # Test direct de l'endpoint de vérification pwned
        resp_pwned = client.post(
            "/auth/check-password-pwned", json={"password": "password123"}
        )
        assert resp_pwned.status_code == 200
        assert resp_pwned.json()["pwned"] is True

        resp_safe = client.post(
            "/auth/check-password-pwned",
            json={"password": "RythmoSecure_VerySafe_998877!@#$%"},
        )
        assert resp_safe.status_code == 200
        assert resp_safe.json()["pwned"] is False

        # Register avec un mot de passe compromis -> 400
        resp_bad_reg = client.post(
            "/auth/register",
            json={
                "email": "pwned_user@example.com",
                "password": "password123",
                "role": "invité",
            },
        )
        assert resp_bad_reg.status_code == 400
        assert "compromis" in resp_bad_reg.json()["detail"].lower()

        # Register avec un mot de passe sécurisé -> 201
        resp_reg = client.post(
            "/auth/register",
            json={
                "email": "test_admin_mfa@example.com",
                "password": "RythmoSecure_Admin_9988!@#",
                "role": "owner",
            },
        )
        assert resp_reg.status_code == 201
        user_data = resp_reg.json()
        assert user_data["email"] == "test_admin_mfa@example.com"
        assert user_data["role"] == "owner"

        # ------------------------------------------------------------------
        # 2. Activation MFA pour un compte administrateur de studio (§15.2)
        # ------------------------------------------------------------------
        # Première connexion avant activation MFA -> mfa_required doit être True
        resp_login = client.post(
            "/auth/login",
            json={
                "email": "test_admin_mfa@example.com",
                "password": "RythmoSecure_Admin_9988!@#",
            },
        )
        assert resp_login.status_code == 200
        login_data = resp_login.json()
        assert login_data["mfa_required"] is True
        assert login_data["mfa_enabled"] is False

        access_token = login_data["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Vérification du statut MFA
        resp_status = client.get("/auth/mfa/status", headers=headers)
        assert resp_status.status_code == 200
        assert resp_status.json()["mfa_enabled"] is False
        assert resp_status.json()["mfa_required"] is True

        # Génération du secret TOTP
        resp_setup = client.post("/auth/mfa/setup", headers=headers)
        assert resp_setup.status_code == 200
        setup_data = resp_setup.json()
        secret = setup_data["secret"]
        assert secret and len(secret) > 10
        assert "otpauth_url" in setup_data

        # Activation / vérification du code TOTP
        totp = pyotp.TOTP(secret)
        valid_code = totp.now()

        # Test avec un code invalide d'abord -> 400
        resp_bad_verify = client.post(
            "/auth/mfa/verify", json={"code": "000000"}, headers=headers
        )
        assert resp_bad_verify.status_code == 400
        assert "invalid totp" in resp_bad_verify.json()["detail"].lower()

        # Test avec le code valide -> 200
        resp_verify = client.post(
            "/auth/mfa/verify", json={"code": valid_code}, headers=headers
        )
        assert resp_verify.status_code == 200
        assert resp_verify.json()["mfa_enabled"] is True

        # Le statut MFA doit maintenant être actif
        resp_status_after = client.get("/auth/mfa/status", headers=headers)
        assert resp_status_after.json()["mfa_enabled"] is True

        # ------------------------------------------------------------------
        # 3. Connexion avec code TOTP obligatoire
        # ------------------------------------------------------------------
        # Tentative de connexion sans code TOTP -> 401 (MFA required)
        resp_login_no_totp = client.post(
            "/auth/login",
            json={
                "email": "test_admin_mfa@example.com",
                "password": "RythmoSecure_Admin_9988!@#",
            },
        )
        assert resp_login_no_totp.status_code == 401
        assert "totp code missing" in resp_login_no_totp.json()["detail"].lower()

        # Tentative de connexion avec un code TOTP erroné -> 401
        resp_login_bad_totp = client.post(
            "/auth/login",
            json={
                "email": "test_admin_mfa@example.com",
                "password": "RythmoSecure_Admin_9988!@#",
                "totp_code": "000000",
            },
        )
        assert resp_login_bad_totp.status_code == 401
        assert "invalid totp code" in resp_login_bad_totp.json()["detail"].lower()

        # Connexion réussie avec le code TOTP valide
        new_valid_code = totp.now()
        resp_login_totp = client.post(
            "/auth/login",
            json={
                "email": "test_admin_mfa@example.com",
                "password": "RythmoSecure_Admin_9988!@#",
                "totp_code": new_valid_code,
            },
        )
        assert resp_login_totp.status_code == 200
        mfa_login_data = resp_login_totp.json()
        assert mfa_login_data["mfa_enabled"] is True
        assert "access_token" in mfa_login_data

        mfa_token = mfa_login_data["access_token"]
        mfa_refresh = mfa_login_data["refresh_token"]
        mfa_headers = {"Authorization": f"Bearer {mfa_token}"}

        # L'accès aux endpoints protégés fonctionne avec le nouveau token
        resp_me = client.get("/auth/me", headers=mfa_headers)
        assert resp_me.status_code == 200
        assert resp_me.json()["email"] == "test_admin_mfa@example.com"

        # ------------------------------------------------------------------
        # 4. Révocation globale des sessions de l'utilisateur
        # ------------------------------------------------------------------
        # Appel de la révocation immédiate de toutes les sessions actives
        resp_revoke = client.post("/auth/revoke-sessions", headers=mfa_headers)
        assert resp_revoke.status_code == 200
        assert (
            "revoked successfully"
            in resp_revoke.json()["message"].lower()
        )

        # L'access token immédiatement invalidé -> 401
        resp_me_after_revoke = client.get("/auth/me", headers=mfa_headers)
        assert resp_me_after_revoke.status_code == 401
        assert "revoked" in resp_me_after_revoke.json()["detail"].lower()

        # Le refresh token également invalidé -> 401
        resp_refresh_after_revoke = client.post(
            "/auth/refresh", json={"refresh_token": mfa_refresh}
        )
        assert resp_refresh_after_revoke.status_code == 401

        # ------------------------------------------------------------------
        # 5. Test complémentaire : Révocation par un administrateur d'un autre utilisateur
        # ------------------------------------------------------------------
        # Création et connexion d'un second utilisateur
        resp_reg_b = client.post(
            "/auth/register",
            json={
                "email": "user_b_mfa@example.com",
                "password": "RythmoSecure_UserB_9988!@#",
                "role": "adaptateur",
            },
        )
        assert resp_reg_b.status_code == 201
        resp_login_b = client.post(
            "/auth/login",
            json={
                "email": "user_b_mfa@example.com",
                "password": "RythmoSecure_UserB_9988!@#",
            },
        )
        assert resp_login_b.status_code == 200
        token_b = resp_login_b.json()["access_token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # Vérification que la session B est active
        assert client.get("/auth/me", headers=headers_b).status_code == 200

        # Connexion de l'administrateur avec TOTP pour obtenir une nouvelle session valide
        admin_code = totp.now()
        resp_login_admin = client.post(
            "/auth/login",
            json={
                "email": "test_admin_mfa@example.com",
                "password": "RythmoSecure_Admin_9988!@#",
                "totp_code": admin_code,
            },
        )
        assert resp_login_admin.status_code == 200
        admin_new_token = resp_login_admin.json()["access_token"]
        headers_admin_new = {"Authorization": f"Bearer {admin_new_token}"}

        # L'administrateur révoque toutes les sessions de user_b_mfa@example.com
        resp_revoke_b = client.post(
            "/auth/revoke-sessions",
            json={"email": "user_b_mfa@example.com"},
            headers=headers_admin_new,
        )
        assert resp_revoke_b.status_code == 200
        assert resp_revoke_b.json()["status"] == "success"

        # Le token de User B est immédiatement invalidé
        assert client.get("/auth/me", headers=headers_b).status_code == 401

    finally:
        cleanup_users()
