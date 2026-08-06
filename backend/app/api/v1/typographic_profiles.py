from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from app.core.security import require_role

router = APIRouter(prefix="/studios/{studio_id}/typographic-profiles", tags=["typographic-profiles"])

class TypographicProfileCreate(BaseModel):
    name: str
    description: Optional[str] = None
    rules: Dict[str, Any]
    is_default: bool = False

class TypographicProfileResponse(BaseModel):
    id: int
    name: str
    rules: Dict[str, Any]
    is_default: bool

# In-memory for MVP
profiles_db = {}

@router.post("", response_model=TypographicProfileResponse)
async def create_profile(studio_id: int, profile: TypographicProfileCreate, 
                         current_user=Depends(require_role("admin"))):
    """G-2.4 — Create typographic profile for a studio."""
    pid = len(profiles_db) + 1
    profiles_db[pid] = {
        "id": pid,
        "studio_id": studio_id,
        "name": profile.name,
        "rules": profile.rules,
        "is_default": profile.is_default
    }
    return profiles_db[pid]

@router.get("", response_model=List[TypographicProfileResponse])
async def list_profiles(studio_id: int, current_user=Depends(require_role("guest"))):
    return [p for p in profiles_db.values() if p["studio_id"] == studio_id]

@router.patch("/{profile_id}")
async def update_profile(studio_id: int, profile_id: int, updates: dict,
                         current_user=Depends(require_role("admin"))):
    if profile_id not in profiles_db:
        raise HTTPException(404, "Profile not found")
    profiles_db[profile_id].update(updates)
    return profiles_db[profile_id]
