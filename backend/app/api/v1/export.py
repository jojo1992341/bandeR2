from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from typing import List, Optional
from app.core.security import require_role
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
from datetime import datetime

router = APIRouter(prefix="/exports", tags=["export"])

class ExportRequest(BaseModel):
    project_id: int
    format: str
    replicas: List[dict]
    username: Optional[str] = "user"

def format_timecode(ms: int) -> str:
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

@router.post("/srt")
async def export_srt(request: ExportRequest, current_user=Depends(require_role("adaptateur"))):
    if request.format != "srt":
        raise HTTPException(400, "format must be srt")
    content = io.StringIO()
    for i, rep in enumerate(request.replicas, 1):
        start = format_timecode(rep["start_ms"])
        end = format_timecode(rep["end_ms"])
        content.write(f"{i}\n{start} --> {end}\n{rep['text']}\n\n")
    return Response(content=content.getvalue(), media_type="text/plain",
                    headers={"Content-Disposition": f"attachment; filename=project_{request.project_id}.srt"})

@router.post("/vtt")
async def export_vtt(request: ExportRequest, current_user=Depends(require_role("adaptateur"))):
    content = io.StringIO()
    content.write("WEBVTT\n\n")
    for rep in request.replicas:
        start = format_timecode(rep["start_ms"]).replace(",", ".")
        end = format_timecode(rep["end_ms"]).replace(",", ".")
        content.write(f"{start} --> {end}\n{rep['text']}\n\n")
    return Response(content=content.getvalue(), media_type="text/vtt",
                    headers={"Content-Disposition": f"attachment; filename=project_{request.project_id}.vtt"})

@router.post("/pdf")
async def export_pdf(request: ExportRequest, current_user=Depends(require_role("adaptateur"))):
    """Export calligraphed PDF (G-1.13) with timecodes and watermark."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20*mm, height - 20*mm, f"RythmoAI - Project #{request.project_id}")
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, height - 28*mm, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | User: {request.username}")
    
    # Watermark for guests
    if request.username in ["guest", "client"]:
        c.saveState()
        c.setFont("Helvetica", 40)
        c.setFillColor(HexColor("#FF0000"))
        c.rotate(45)
        c.drawString(50*mm, 100*mm, "CONFIDENTIAL")
        c.restoreState()
    
    # Content
    y = height - 45*mm
    c.setFont("Helvetica", 9)
    
    for i, rep in enumerate(request.replicas):
        if y < 25*mm:
            c.showPage()
            y = height - 25*mm
        
        start_tc = format_timecode(rep["start_ms"])
        end_tc = format_timecode(rep["end_ms"])
        
        # Timecode
        c.setFillColor(HexColor("#333333"))
        c.drawString(20*mm, y, f"{start_tc} → {end_tc}")
        
        # Text
        c.setFillColor(HexColor("#000000"))
        c.drawString(55*mm, y, rep.get("text", "")[:90])
        
        # Speaker / confidence
        c.setFont("Helvetica", 7)
        c.setFillColor(HexColor("#666666"))
        c.drawString(20*mm, y - 4*mm, f"Speaker {rep.get('speaker_id', 1)} | conf: {rep.get('confidence_score', 0.85):.2f}")
        c.setFont("Helvetica", 9)
        
        y -= 12*mm
    
    c.save()
    buffer.seek(0)
    
    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=project_{request.project_id}.pdf"}
    )
