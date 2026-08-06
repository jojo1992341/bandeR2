from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import require_role
from typing import Optional

router = APIRouter(prefix="/sso", tags=["sso"])

class SSOInitiateResponse(BaseModel):
    redirect_url: str
    state: str

class SSOCallbackRequest(BaseModel):
    code: str
    state: str

@router.get("/initiate/{provider}")
async def initiate_sso(provider: str, current_user=Depends(require_role("guest"))):
    """G-4.1 — SSO Enterprise (Azure AD / Okta placeholder)."""
    if provider not in ["azure", "okta"]:
        raise HTTPException(400, "Unsupported provider")
    
    # Placeholder redirect (real impl would generate proper SAML/OIDC URL)
    return SSOInitiateResponse(
        redirect_url=f"https://{provider}.example.com/oauth2/authorize?client_id=rythmoai&state=abc123",
        state="abc123"
    )

@router.post("/callback")
async def sso_callback(request: SSOCallbackRequest, current_user=Depends(require_role("guest"))):
    """Handle SSO callback and map claims to roles."""
    # Placeholder: would validate token and create/update user
    return {
        "access_token": "fake-jwt-from-sso",
        "user": {"email": "user@studio.com", "role": "chef_projet", "studio_id": 1}
    }
