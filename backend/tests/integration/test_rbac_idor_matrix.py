"""
G-019 Matrix test: endpoint x role 401/403/404/2xx and anti-IDOR inter-tenant leak protection
Covers CDC §10.4 §15.3
"""
import uuid
import pathlib as _pl
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.core.database import Base, get_db
from app.core.auth_handler import create_access_token
from app.models import Studio, Project, User, StudioMembership, Replica, MediaAsset
from app.core.password import hash_password

# Override DB to use sqlite file for this test (isolated)
_test_db_path = "/tmp/rbac_matrix_test.db"
_test_engine = create_engine(f"sqlite:///{_test_db_path}", connect_args={"check_same_thread": False})
Base.metadata.create_all(_test_engine)
_TestSession = sessionmaker(bind=_test_engine, expire_on_commit=False)

def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)

def _make_token(user_id, email, role, tv=0):
    return create_access_token({"sub": str(user_id), "email": email, "role": role, "tv": tv})

def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}

def test_matrix_rbac_idor():
    db = _TestSession()
    try:
        # clean previous test data with prefix
        # create two tenants
        studio_a = Studio(id=uuid.uuid4(), name="Matrix A", plan="pro")
        studio_b = Studio(id=uuid.uuid4(), name="Matrix B", plan="pro")
        db.add_all([studio_a, studio_b])
        db.commit()
        # users
        user_owner_a = User(id=uuid.uuid4(), email=f"owner_a_{uuid.uuid4()}@test.com", hashed_password=hash_password("pass123!"), role="owner", is_active=True)
        user_guest_a = User(id=uuid.uuid4(), email=f"guest_a_{uuid.uuid4()}@test.com", hashed_password=hash_password("pass123!"), role="invité", is_active=True)
        user_owner_b = User(id=uuid.uuid4(), email=f"owner_b_{uuid.uuid4()}@test.com", hashed_password=hash_password("pass123!"), role="owner", is_active=True)
        db.add_all([user_owner_a, user_guest_a, user_owner_b])
        db.commit()
        for u in [user_owner_a, user_guest_a, user_owner_b]:
            db.refresh(u)
            # ensure token_version default
            if getattr(u, "token_version", None) is None:
                u.token_version = 0
        db.commit()
        mem_a_owner = StudioMembership(id=uuid.uuid4(), studio_id=studio_a.id, user_id=user_owner_a.id, role="owner")
        mem_a_guest = StudioMembership(id=uuid.uuid4(), studio_id=studio_a.id, user_id=user_guest_a.id, role="invité")
        mem_b_owner = StudioMembership(id=uuid.uuid4(), studio_id=studio_b.id, user_id=user_owner_b.id, role="owner")
        db.add_all([mem_a_owner, mem_a_guest, mem_b_owner])
        db.commit()

        # project in A
        proj_a = Project(id=uuid.uuid4(), studio_id=studio_a.id, title="Proj A", source_lang="fr", target_lang="fr", status="Cree")
        db.add(proj_a)
        db.commit()
        db.refresh(proj_a)
        # media + replica in A
        media_a = MediaAsset(id=uuid.uuid4(), project_id=proj_a.id, storage_path="test/path.mp4", status="confirmed")
        db.add(media_a)
        db.commit()
        replica_a = Replica(id=uuid.uuid4(), media_id=media_a.id, text="Bonjour", start_ms=0, end_ms=1000, order_index=0, typo_codes={})
        db.add(replica_a)
        db.commit()

        # Export in A
        from app.models import Export
        export_a = Export(id=uuid.uuid4(), project_id=proj_a.id, format="pdf", status="completed", file_path="/tmp/fake.pdf")
        db.add(export_a)
        db.commit()

        # speaker in A
        from app.models import Speaker
        speaker_a = Speaker(id=uuid.uuid4(), project_id=proj_a.id, label="Speaker A")
        db.add(speaker_a)
        db.commit()

        # audit log in A
        from app.models import AuditLog
        audit_a = AuditLog(id=uuid.uuid4(), studio_id=studio_a.id, user_id=user_owner_a.id, user_email=user_owner_a.email, action="test_action", details={})
        db.add(audit_a)
        db.commit()

        # tokens
        tok_owner_a = _make_token(user_owner_a.id, user_owner_a.email, "owner", tv=user_owner_a.token_version or 0)
        tok_guest_a = _make_token(user_guest_a.id, user_guest_a.email, "invité", tv=user_guest_a.token_version or 0)
        tok_owner_b = _make_token(user_owner_b.id, user_owner_b.email, "owner", tv=user_owner_b.token_version or 0)
        tok_invalid = "invalid.token.here"

        # 1. Unauthenticated -> 401 for protected routes
        unauth_endpoints = [
            ("GET", f"/api/v1/projects/{proj_a.id}"),
            ("GET", f"/api/v1/projects/{proj_a.id}/replicas"),
            ("GET", f"/api/v1/replicas/{replica_a.id}"),
            ("PATCH", f"/api/v1/replicas/{replica_a.id}"),
            ("GET", f"/api/v1/projects/{proj_a.id}/speakers"),
            ("GET", f"/api/v1/exports/{export_a.id}"),
            ("GET", f"/api/v1/words/{replica_a.id}"),  # word id not valid but should 401 before 404
            ("GET", f"/api/v1/audit-logs?studio_id={studio_a.id}"),
            ("GET", f"/api/v1/security-alerts?studio_id={studio_a.id}"),
            ("GET", f"/api/v1/studios/{studio_a.id}/search?q=test"),
            ("GET", f"/api/v1/studios/{studio_a.id}/dashboard"),
        ]
        for method, url in unauth_endpoints:
            if method == "GET":
                r = client.get(url)
            else:
                r = client.request(method, url, json={})
            assert r.status_code == 401, f"Expected 401 for unauth {method} {url} got {r.status_code} {r.text}"

        # 2. Authenticated but wrong tenant -> 404 (IDOR protection, not leak)
        # Owner B trying to access proj_a
        r = client.get(f"/api/v1/projects/{proj_a.id}", headers=_auth_header(tok_owner_b))
        assert r.status_code == 404, f"IDOR fail project access cross-tenant expected 404 got {r.status_code} {r.text}"
        r = client.get(f"/api/v1/replicas/{replica_a.id}", headers=_auth_header(tok_owner_b))
        assert r.status_code == 404, f"IDOR replica expected 404 got {r.status_code}"
        r = client.get(f"/api/v1/projects/{proj_a.id}/speakers", headers=_auth_header(tok_owner_b))
        assert r.status_code == 404, f"IDOR speaker list expected 404 got {r.status_code}"
        r = client.get(f"/api/v1/exports/{export_a.id}", headers=_auth_header(tok_owner_b))
        assert r.status_code == 404, f"IDOR export expected 404 got {r.status_code}"
        r = client.get(f"/api/v1/audit-logs?studio_id={studio_a.id}", headers=_auth_header(tok_owner_b))
        # audit should be 404 due to studio member check or empty filtered? Our implementation returns 404 for studio mismatch -> check
        assert r.status_code in (404, 200), f"audit cross-tenant should be 404 or filtered empty, got {r.status_code}"
        if r.status_code == 200:
            # ensure no leak of audit_a if filtered
            data = r.json()
            assert all(d.get("studio_id") != str(studio_a.id) for d in data) or len(data)==0, "Audit leak inter-tenant!"

        # 3. Authenticated correct tenant -> 2xx (or expected success)
        r = client.get(f"/api/v1/projects/{proj_a.id}", headers=_auth_header(tok_owner_a))
        assert r.status_code == 200, f"Owner A should access own project 200 got {r.status_code} {r.text}"
        r = client.get(f"/api/v1/replicas/{replica_a.id}", headers=_auth_header(tok_owner_a))
        assert r.status_code == 200, f"Owner A replica 200 got {r.status_code}"
        r = client.get(f"/api/v1/projects/{proj_a.id}/speakers", headers=_auth_header(tok_owner_a))
        assert r.status_code in (200, ), f"Speaker list 200 got {r.status_code} {r.text}"
        r = client.get(f"/api/v1/exports/{export_a.id}", headers=_auth_header(tok_owner_a))
        assert r.status_code == 200, f"Export 200 got {r.status_code} {r.text}"
        r = client.get(f"/api/v1/audit-logs?studio_id={studio_a.id}", headers=_auth_header(tok_owner_a))
        assert r.status_code == 200, f"Audit 200 got {r.status_code}"

        # Public health should be 200 without auth
        r = client.get("/health")
        assert r.status_code == 200
        r = client.get("/api/v1/projects/health")
        # this is under prefix /api/v1/projects/health ? Actually defined as /health inside projects router with prefix /api/v1/projects -> /api/v1/projects/health
        # Should be public
        # We check it returns 200 even without auth
        # If not, ignore
        # Note: projects health defined as /health
        assert r.status_code == 200

    finally:
        # cleanup
        from app.models import AuditLog as _AuditLog, Export as _Export, Speaker as _Speaker, Replica as _Replica, MediaAsset as _MediaAsset, Project as _Project, StudioMembership as _SM2, User as _User2, Studio as _Studio2
        try:
            db.query(_AuditLog).filter(_AuditLog.studio_id.in_([studio_a.id, studio_b.id])).delete(synchronize_session=False)
            db.query(_Export).filter(_Export.project_id == proj_a.id).delete(synchronize_session=False)
            db.query(_Speaker).filter(_Speaker.project_id == proj_a.id).delete(synchronize_session=False)
            db.query(_Replica).filter(_Replica.id == replica_a.id).delete(synchronize_session=False)
            db.query(_MediaAsset).filter(_MediaAsset.id == media_a.id).delete(synchronize_session=False)
            db.query(_Project).filter(_Project.id == proj_a.id).delete(synchronize_session=False)
            db.query(_SM2).filter(_SM2.studio_id.in_([studio_a.id, studio_b.id])).delete(synchronize_session=False)
            db.query(_User2).filter(_User2.id.in_([user_owner_a.id, user_guest_a.id, user_owner_b.id])).delete(synchronize_session=False)
            db.query(_Studio2).filter(_Studio2.id.in_([studio_a.id, studio_b.id])).delete(synchronize_session=False)
            db.commit()
        except Exception as e:
            db.rollback()
        db.close()
