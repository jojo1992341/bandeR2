import uuid
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.auth_handler import verify_token
from app.core.config import get_settings
from app.core.database import get_db

security = HTTPBearer(auto_error=False)

ROLE_ORDER = {
    "owner": 6,
    "admin": 6,
    "chef_de_projet": 5,
    "directeur_artistique": 4,
    "adaptateur": 3,
    "calligraphe": 3,
    "invité": 1,
    "guest": 1,
}

RISKY_ROLES = {
    "invité",
    "invite",
    "guest",
    "client",
    "client_externe",
    "externe",
    "viewer",
}


def is_risky_role(role: str) -> bool:
    if not role:
        return False
    r = role.lower().strip()
    return r in RISKY_ROLES or "invit" in r or "client" in r or "extern" in r


def normalize_role(role: str) -> str:
    r = role.lower().replace(" ", "_").replace("/", "_")
    return r


def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_token(credentials.credentials, token_type="access")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    sub = payload.get("sub")
    if sub:
        try:
            from app.models import User

            user = db.query(User).filter(User.id == uuid.UUID(str(sub))).first()
            if user:
                token_tv = payload.get("tv", 0)
                user_tv = getattr(user, "token_version", 0) or 0
                if token_tv != user_tv:
                    raise HTTPException(status_code=401, detail="Token revoked")
        except HTTPException:
            raise
        except Exception:
            pass
    return payload


def get_optional_user_payload(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[dict]:
    if not credentials:
        return None
    try:
        payload = verify_token(credentials.credentials, token_type="access")
        if payload:
            return payload
    except Exception:
        pass
    return None


def require_role(*allowed_roles: str):
    allowed = [normalize_role(r) for r in allowed_roles]

    def dependency(payload: dict = Depends(get_current_user_payload)):
        user_role = normalize_role(payload.get("role", "invité"))
        if user_role not in allowed:
            raise HTTPException(
                status_code=403, detail="Insufficient permissions"
            )
        return payload

    return dependency


# ── Centralized studio/project access helpers (§10.4 anti-IDOR) ──

def _get_user_id(payload: dict):
    import uuid as _uuid
    from fastapi import HTTPException as _HE
    sub = payload.get("sub")
    if not sub:
        raise _HE(status_code=401, detail="Not authenticated")
    try:
        return _uuid.UUID(str(sub))
    except Exception:
        raise _HE(status_code=401, detail="Invalid token subject")


def assert_studio_member(db, user_id, studio_id):
    from fastapi import HTTPException as _HE
    from app.models import StudioMembership, User, Studio
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise _HE(status_code=404, detail="Studio not found")
    membership = (
        db.query(StudioMembership)
        .filter(StudioMembership.studio_id == studio_id, StudioMembership.user_id == user_id)
        .first()
    )
    if membership:
        return
    user = db.query(User).filter(User.id == user_id).first()
    any_mem = db.query(StudioMembership).filter(StudioMembership.user_id == user_id).first()
    if not any_mem and user and normalize_role(user.role) in ("owner", "admin"):
        return
    raise _HE(status_code=404, detail="Studio not found or access denied (§10.4 IDOR)")


def require_studio_access_func(studio_id, db, payload):
    user_id = _get_user_id(payload)
    assert_studio_member(db, user_id, studio_id)
    return payload


def assert_project_access(db, user_id, project_id):
    from app.models import Project
    from fastapi import HTTPException as _HE
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise _HE(status_code=404, detail="Project not found")
    assert_studio_member(db, user_id, project.studio_id)
    return project


def assert_replica_access(db, user_id, replica_id):
    from app.models import Replica, MediaAsset, Project
    from fastapi import HTTPException as _HE
    replica = db.query(Replica).filter(Replica.id == replica_id).first()
    if not replica:
        raise _HE(status_code=404, detail="Replica not found")
    media = db.query(MediaAsset).filter(MediaAsset.id == replica.media_id).first()
    if not media:
        raise _HE(status_code=404, detail="Project not found for replica")
    project = db.query(Project).filter(Project.id == media.project_id).first()
    if not project:
        raise _HE(status_code=404, detail="Project not found")
    assert_studio_member(db, user_id, project.studio_id)
    return replica


def assert_media_access(db, user_id, media_id):
    from app.models import MediaAsset, Project
    from fastapi import HTTPException as _HE
    media = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not media:
        raise _HE(status_code=404, detail="Media not found")
    project = db.query(Project).filter(Project.id == media.project_id).first()
    if not project:
        raise _HE(status_code=404, detail="Project not found")
    assert_studio_member(db, user_id, project.studio_id)
    return media


def assert_export_access(db, user_id, export_id):
    from app.models import Export, Project
    from fastapi import HTTPException as _HE
    exp = db.query(Export).filter(Export.id == export_id).first()
    if not exp:
        raise _HE(status_code=404, detail="Export not found")
    project = db.query(Project).filter(Project.id == exp.project_id).first()
    if not project:
        raise _HE(status_code=404, detail="Project not found for export")
    assert_studio_member(db, user_id, project.studio_id)
    return exp
