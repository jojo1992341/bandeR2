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
