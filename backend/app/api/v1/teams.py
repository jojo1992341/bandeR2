from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.core.security import require_role

router = APIRouter(prefix="/studios/{studio_id}/teams", tags=["teams"])

class TeamCreate(BaseModel):
    name: str
    description: Optional[str] = None
    members: List[int] = []

@router.post("")
async def create_team(studio_id: int, team: TeamCreate, current_user=Depends(require_role("admin"))):
    """G-4.2 — Create sub-teams / groups within studio."""
    return {
        "id": 1,
        "studio_id": studio_id,
        "name": team.name,
        "members": team.members,
        "message": "Team created (Enterprise feature)"
    }

@router.get("")
async def list_teams(studio_id: int, current_user=Depends(require_role("guest"))):
    return [
        {"id": 1, "name": "Pôle jeunesse", "member_count": 8},
        {"id": 2, "name": "Pôle films", "member_count": 14}
    ]
