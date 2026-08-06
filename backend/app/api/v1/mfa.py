from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import require_role
import pyotp
import secrets

router = APIRouter(prefix="/mfa", tags=["mfa"])

class MFAEnableRequest(BaseModel):
    user_id: int

class MFAVerifyRequest(BaseModel):
    user_id: int
    code: str

# In-memory TOTP secrets for MVP
totp_secrets = {}

@router.post("/enable")
async def enable_mfa(request: MFAEnableRequest, current_user=Depends(require_role("admin"))):
    """G-2.10 — Enable TOTP MFA for admin accounts."""
    secret = pyotp.random_base32()
    totp_secrets[request.user_id] = secret
    
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=f"user{request.user_id}@rythmoai.com", issuer_name="RythmoAI")
    
    return {
        "secret": secret,
        "provisioning_uri": provisioning_uri,
        "message": "Scan QR code with authenticator app"
    }

@router.post("/verify")
async def verify_mfa(request: MFAVerifyRequest, current_user=Depends(require_role("guest"))):
    secret = totp_secrets.get(request.user_id)
    if not secret:
        raise HTTPException(400, "MFA not enabled for this user")
    
    totp = pyotp.TOTP(secret)
    if totp.verify(request.code):
        return {"verified": True, "message": "MFA successful"}
    raise HTTPException(401, "Invalid MFA code")
