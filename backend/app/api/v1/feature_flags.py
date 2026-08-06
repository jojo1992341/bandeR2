from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Dict
from app.core.security import require_role

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])

class FeatureFlagUpdate(BaseModel):
    lip_sync_enabled: bool = False

# Global feature flags (in production: Redis or DB)
flags = {
    "lip_sync_enabled": False
}

@router.get("")
async def get_flags(current_user=Depends(require_role("guest"))):
    return flags

@router.patch("")
async def update_flags(update: FeatureFlagUpdate, current_user=Depends(require_role("admin"))):
    """G-3.3 — Feature flag for lip sync (disabled by default)."""
    global flags
    flags["lip_sync_enabled"] = update.lip_sync_enabled
    return flags
