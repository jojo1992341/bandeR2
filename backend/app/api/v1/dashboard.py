from fastapi import APIRouter, Depends
from app.core.security import require_role
from app.services.dashboard import get_studio_dashboard

router = APIRouter(prefix="/studios/{studio_id}/dashboard", tags=["dashboard"])

@router.get("")
async def studio_dashboard(studio_id: int, current_user=Depends(require_role("chef_projet"))):
    """G-3.4 — Studio advanced dashboard."""
    return get_studio_dashboard(studio_id)
