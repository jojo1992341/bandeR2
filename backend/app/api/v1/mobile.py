from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List
from app.core.security import require_role

router = APIRouter(prefix="/mobile", tags=["mobile"])

class ProjectSummary(BaseModel):
    id: int
    title: str
    status: str
    last_updated: str

@router.get("/projects", response_model=List[ProjectSummary])
async def mobile_projects(current_user=Depends(require_role("guest"))):
    """G-4.6 — Mobile read-only consultation app (no editing)."""
    # RBAC ensures no write endpoints are exposed to mobile role
    return [
        {"id": 1, "title": "Film Test", "status": "validated", "last_updated": "2026-08-05"},
        {"id": 2, "title": "Série Épisode 3", "status": "editing", "last_updated": "2026-08-06"}
    ]

@router.get("/projects/{project_id}/comments")
async def mobile_comments(project_id: int, current_user=Depends(require_role("guest"))):
    """Read-only comments for mobile supervision."""
    return [{"id": 1, "text": "À valider avant vendredi", "author": "DA"}]
