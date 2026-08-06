from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.core.security import require_role
from app.services.rythmo_generator import generate_rythmo_band_from_transcript

router = APIRouter(prefix="/rythmo", tags=["rythmo"])

class GenerateRequest(BaseModel):
    project_id: int
    media_asset_id: int
    transcript: dict
    profile_id: Optional[int] = None

class ReplicaResponse(BaseModel):
    order_index: int
    start_ms: int
    end_ms: int
    text: str
    speaker_id: Optional[int]
    confidence_score: float

@router.post("/generate", response_model=List[ReplicaResponse])
async def generate_rythmo(
    request: GenerateRequest,
    current_user=Depends(require_role("adaptateur"))
):
    """
    Generate RythmoBand from transcript (G-1.8).
    Returns list of replicas ready for editing.
    """
    replicas = generate_rythmo_band_from_transcript(request.transcript)
    
    if not replicas:
        raise HTTPException(status_code=400, detail="No valid segments in transcript")
    
    return replicas

@router.post("/replicas/{replica_id}/split")
async def split_replica(
    replica_id: int,
    split_ms: int,
    current_user=Depends(require_role("adaptateur"))
):
    """Split a replica at given timestamp (G-1.10)."""
    # Placeholder - would update DB in real impl
    return {"status": "split", "replica_id": replica_id, "split_at": split_ms}

@router.post("/replicas/merge")
async def merge_replicas(
    replica_ids: List[int],
    current_user=Depends(require_role("adaptateur"))
):
    """Merge multiple replicas (G-1.10)."""
    return {"status": "merged", "replica_ids": replica_ids}
