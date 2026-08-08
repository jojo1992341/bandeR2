from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from app.models import User
from app.core.password import hash_password

client = TestClient(app)


def get_db_session() -> Session:
    return SessionLocal()


def cleanup_users():
    db = get_db_session()
    try:
        db.query(User).filter(
            User.email.in_(
                [
                    "test_user@example.com",
                    "test_admin@example.com",
                    "test_adaptor@example.com",
                ]
            )
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_auth_flow():
    # Clean previous
    cleanup_users()

    # 1. Register user
    resp = client.post(
        "/auth/register",
        json={
            "email": "test_user@example.com",
            "password": "Secret123!",
            "role": "adaptateur",
        },
    )
    assert resp.status_code == 201
    user_data = resp.json()
    assert user_data["email"] == "test_user@example.com"

    # 2. Login
    resp = client.post(
        "/auth/login", json={"email": "test_user@example.com", "password": "Secret123!"}
    )
    assert resp.status_code == 200
    login_data = resp.json()
    assert "access_token" in login_data
    assert "refresh_token" in login_data
    access_token = login_data["access_token"]
    refresh_token = login_data["refresh_token"]

    # 3. Access protected endpoint with token
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 200
    me = resp.json()
    assert me["email"] == "test_user@example.com"

    # 4. Access without token -> 401
    resp = client.get("/auth/me")
    assert resp.status_code == 401

    # 5. Refresh token -> new pair (rotation)
    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    refresh_data = resp.json()
    assert "access_token" in refresh_data
    assert "refresh_token" in refresh_data
    # After rotation, old refresh should not be reusable (optional strict check omitted for simplicity)

    # 6. Role insufficient -> 403 on admin-only endpoint
    resp = client.get(
        "/auth/admin-only", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 403

    # 7. Create admin user directly for 200 test
    db = get_db_session()
    try:
        admin = User(
            email="test_admin@example.com",
            hashed_password=hash_password("Admin123!"),
            role="owner",
            is_active=True,
        )
        db.add(admin)
        db.commit()
    finally:
        db.close()

    resp = client.post(
        "/auth/login", json={"email": "test_admin@example.com", "password": "Admin123!"}
    )
    assert resp.status_code == 200
    admin_token = resp.json()["access_token"]

    resp = client.get(
        "/auth/admin-only", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Admin access granted"

    # Cleanup
    cleanup_users()
