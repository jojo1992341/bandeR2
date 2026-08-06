from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.core.security import require_role
from datetime import datetime

router = APIRouter(prefix="/projects", tags=["projects"])

class ProjectCreate(BaseModel):
    title: str
    studio_id: int

class ProjectResponse(BaseModel):
    id: int
    title: str
    studio_id: int
    status: str
    created_at: str

# In-memory store for MVP (replace with DB later)
projects_db = {}

@router.post("", response_model=ProjectResponse)
async def create_project(project: ProjectCreate, current_user=Depends(require_role("chef_projet"))):
    """Create project with lifecycle (G-1.14)."""
    pid = len(projects_db) + 1
    projects_db[pid] = {
        "id": pid,
        "title": project.title,
        "studio_id": project.studio_id,
        "status": "created",
        "created_at": datetime.now().isoformat()
    }
    return projects_db[pid]

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int, current_user=Depends(require_role("guest"))):
    if project_id not in projects_db:
        raise HTTPException(404, "Project not found")
    return projects_db[project_id]

@router.patch("/{project_id}/status")
async def update_status(project_id: int, status: str, current_user=Depends(require_role("chef_projet"))):
    """Project lifecycle transitions (G-1.14)."""
    allowed = ["created", "processing", "ready_for_edit", "editing", "review", "validated", "exported", "archived"]
    if status not in allowed:
        raise HTTPException(400, "Invalid status")
    if project_id not in projects_db:
        raise HTTPException(404, "Project not found")
    projects_db[project_id]["status"] = status
    return {"id": project_id, "status": status}

@router.post("/{project_id}/invite")
async def invite_user(project_id: int, email: str, role: str, current_user=Depends(require_role("admin"))):
    """Invite user to project/studio (G-1.14)."""
    return {"message": f"Invitation sent to {email} with role {role}"}
