from fastapi import APIRouter, Depends, Query
from typing import List
from app.core.security import require_role
from app.services.search import full_text_search

router = APIRouter(prefix="/search", tags=["search"])

@router.get("/transcriptions")
async def search_transcriptions(
    q: str = Query(..., min_length=2),
    studio_id: int = 1,
    limit: int = 20,
    current_user=Depends(require_role("guest"))
):
    """G-3.5 — Full-text search across all studio projects."""
    return full_text_search(studio_id, q, limit)
