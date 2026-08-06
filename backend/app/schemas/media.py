from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class MediaAssetBase(BaseModel):
    filename: str
    project_id: int

class MediaAssetCreate(MediaAssetBase):
    pass

class MediaAsset(MediaAssetBase):
    id: int
    duration_ms: int = 0
    storage_path: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class UploadUrlResponse(BaseModel):
    upload_url: str
    object_name: str
    expires_in: int = 3600
