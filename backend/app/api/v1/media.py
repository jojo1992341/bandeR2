from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.schemas.media import UploadUrlResponse, MediaAsset
from app.infrastructure.storage import get_presigned_upload_url
from app.core.security import require_role
import uuid

router = APIRouter(prefix="/media", tags=["media"])

class UploadRequest(BaseModel):
    filename: str
    project_id: int
    content_type: str = "video/mp4"

@router.post("/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(
    request: UploadRequest,
    current_user=Depends(require_role("adaptateur"))
):
    """Generate pre-signed URL for resumable video upload (US-001, US-002)."""
    if not request.filename.lower().endswith(('.mp4', '.mov', '.mxf', '.avi', '.mkv')):
        raise HTTPException(status_code=400, detail="Unsupported video format")
    
    object_name = f"projects/{request.project_id}/uploads/{uuid.uuid4()}-{request.filename}"
    
    upload_url = get_presigned_upload_url(object_name, expires=3600)
    
    return UploadUrlResponse(
        upload_url=upload_url,
        object_name=object_name,
        expires_in=3600
    )

@router.post("/projects/{project_id}/media", response_model=MediaAsset)
async def create_media_asset(
    project_id: int,
    filename: str,
    storage_path: str,
    current_user=Depends(require_role("adaptateur"))
):
    """Register uploaded media asset after successful upload."""
    # In real impl: save to DB
    return MediaAsset(
        id=1,
        filename=filename,
        project_id=project_id,
        duration_ms=0,
        storage_path=storage_path
    )
