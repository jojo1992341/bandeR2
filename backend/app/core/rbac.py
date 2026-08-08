from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List
from app.core.auth_handler import verify_token
from app.core.config import get_settings

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


def normalize_role(role: str) -> str:
    r = role.lower().replace(" ", "_").replace("/", "_")
    return r


def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_token(credentials.credentials, token_type="access")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


def require_role(*allowed_roles: str):
    allowed = [normalize_role(r) for r in allowed_roles]

    def dependency(payload: dict = Depends(get_current_user_payload)):
        user_role = normalize_role(payload.get("role", "invité"))
        if user_role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return payload

    return dependency
