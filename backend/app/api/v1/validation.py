from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import require_role
from datetime import datetime

router = APIRouter(prefix="/validation", tags=["validation"])

class ValidationRequest(BaseModel):
    rythmo_band_id: int
    comment: str = ""

@router.post("/validate")
async def validate_band(request: ValidationRequest, current_user=Depends(require_role("directeur_artistique"))):
    """
    G-2.9 — Formal validation by Artistic Director.
    Locks the band (status = "validated").
    """
    # In real impl: update DB status + create audit log
    return {
        "status": "validated",
        "rythmo_band_id": request.rythmo_band_id,
        "validated_by": current_user.sub,
        "validated_at": datetime.now().isoformat(),
        "comment": request.comment,
        "locked": True
    }

@router.post("/unlock")
async def unlock_band(rythmo_band_id: int, current_user=Depends(require_role("chef_projet"))):
    """Unlock a validated band (requires Chef de projet role)."""
    return {
        "status": "unlocked",
        "rythmo_band_id": rythmo_band_id,
        "unlocked_by": current_user.sub
    }
