from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from typing import List
from app.core.security import require_role
import io

router = APIRouter(prefix="/exports", tags=["export"])

class ExportRequest(BaseModel):
    project_id: int
    format: str  # srt, vtt, pdf
    replicas: List[dict]

def format_timecode(ms: int) -> str:
    """Convert milliseconds to SRT/VTT timecode."""
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

@router.post("/srt")
async def export_srt(
    request: ExportRequest,
    current_user=Depends(require_role("adaptateur"))
):
    """Export to SRT format (G-1.12)."""
    if request.format != "srt":
        raise HTTPException(400, "format must be srt")
    
    content = io.StringIO()
    for i, rep in enumerate(request.replicas, 1):
        start = format_timecode(rep["start_ms"])
        end = format_timecode(rep["end_ms"])
        content.write(f"{i}\n{start} --> {end}\n{rep['text']}\n\n")
    
    return Response(
        content=content.getvalue(),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=project_{request.project_id}.srt"}
    )

@router.post("/vtt")
async def export_vtt(
    request: ExportRequest,
    current_user=Depends(require_role("adaptateur"))
):
    """Export to VTT format (G-1.12)."""
    content = io.StringIO()
    content.write("WEBVTT\n\n")
    
    for rep in request.replicas:
        start = format_timecode(rep["start_ms"]).replace(",", ".")
        end = format_timecode(rep["end_ms"]).replace(",", ".")
        content.write(f"{start} --> {end}\n{rep['text']}\n\n")
    
    return Response(
        content=content.getvalue(),
        media_type="text/vtt",
        headers={"Content-Disposition": f"attachment; filename=project_{request.project_id}.vtt"}
    )
