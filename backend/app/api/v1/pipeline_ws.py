import uuid
import time
from typing import Dict, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, get_db
from app.models import PipelineJob, Project
from pydantic import BaseModel

router = APIRouter()

# Gestionnaire de connexions simple (par projet)
ws_connections: Dict[str, List[WebSocket]] = {}

class PipelineStatusOut(BaseModel):
    status: str
    progress_percent: int
    current_step: str
    updated_at: str | None

@router.websocket("/ws/projects/{project_id}/pipeline")
async def ws_pipeline(websocket: WebSocket, project_id: uuid.UUID):
    await websocket.accept()
    key = str(project_id)
    ws_connections.setdefault(key, []).append(websocket)

    # Créer / mettre à jour PipelineJob initial
    db = SessionLocal()
    try:
        job = db.query(PipelineJob).filter(PipelineJob.project_id == project_id).first()
        if not job:
            # Vérifier que le projet existe (anti-IDOR simplifié via DB)
            proj = db.query(Project).filter(Project.id == project_id).first()
            if not proj:
                await websocket.send_json({"error": "Projet non trouvé"})
                await websocket.close()
                return
            job = PipelineJob(
                id=uuid.uuid4(),
                project_id=project_id,
                status="processing",
                progress_percent=0,
                current_step="extraction",
            )
            db.add(job)
            db.commit()
            db.refresh(job)
        else:
            # Réinitialiser si terminé ou échoué
            if job.status in ("completed", "failed"):
                job.status = "processing"
                job.progress_percent = 0
                job.current_step = "extraction"
                db.commit()
        # Envoyer statut initial
        await websocket.send_json({
            "type": "status",
            "status": job.status,
            "progress_percent": job.progress_percent,
            "current_step": job.current_step,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        })
    finally:
        db.close()

    try:
        # Simulation de progression (3 mises à jour distinctes)
        for step_name, pct in [("extraction", 25), ("transcription", 55), ("diarisation", 80)]:
            await websocket.receive_text()  # attend la demande du client pour avancer (ou timeout)
            # En production, le worker Celery mettrait à jour la DB
            db = SessionLocal()
            try:
                job = db.query(PipelineJob).filter(PipelineJob.project_id == project_id).first()
                if job:
                    job.status = "processing"
                    job.progress_percent = pct
                    job.current_step = step_name
                    db.commit()
                    await websocket.send_json({
                        "type": "progress",
                        "status": job.status,
                        "progress_percent": job.progress_percent,
                        "current_step": job.current_step,
                        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                    })
            finally:
                db.close()
        # Final
        db = SessionLocal()
        try:
            job = db.query(PipelineJob).filter(PipelineJob.project_id == project_id).first()
            if job:
                job.status = "completed"
                job.progress_percent = 100
                job.current_step = "export"
                db.commit()
                await websocket.send_json({
                    "type": "completed",
                    "status": job.status,
                    "progress_percent": job.progress_percent,
                    "current_step": job.current_step,
                    "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                })
        finally:
            db.close()
    except WebSocketDisconnect:
        pass
    finally:
        ws_connections.setdefault(key, []).remove(websocket)

@router.get("/projects/{project_id}/pipeline/status", response_model=PipelineStatusOut)
def pipeline_status(project_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.query(PipelineJob).filter(PipelineJob.project_id == project_id).order_by(PipelineJob.updated_at.desc()).first()
    if not job:
        raise HTTPException(status_code=404, detail="Pipeline non trouvé")
    return PipelineStatusOut(
        status=job.status,
        progress_percent=job.progress_percent,
        current_step=job.current_step,
        updated_at=job.updated_at.isoformat() if job.updated_at else None,
    )
