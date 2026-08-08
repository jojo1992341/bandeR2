import uuid
import subprocess
import os
from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth_handler import verify_token
from app.core.rbac import get_current_user_payload, require_role
from app.core.storage import generate_upload_url, get_s3_client
from app.core.config import get_settings
from app.models import MediaAsset, Project
from app.repositories.project_repo import ProjectRepo
from app.repositories.media_asset_repo import MediaAssetRepo

router = APIRouter()

ALLOWED_FORMAT_FRAGMENTS = {"mp4", "mov", "mxf", "avi", "matroska", "h264"}


def _detect_format(path: str) -> str:
    try:
        import av

        with av.open(path) as container:
            if container.format and container.format.name:
                return container.format.name.lower()
    except Exception:
        pass
    try:
        import shutil

        p = shutil.which("ffprobe") or "ffprobe"
        result = subprocess.run(
            [
                p,
                "-v",
                "error",
                "-show_entries",
                "format=format_name",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout:
            return result.stdout.strip().lower().split(",")[0]
    except Exception:
        pass
    return "unknown"


class UploadUrlIn(BaseModel):
    filename: str = Field(..., min_length=1)
    content_type: str = Field(default="video/mp4")


class UploadUrlOut(BaseModel):
    upload_url: str
    media_id: str
    key: str
    expires_in: int = 600


class ConfirmIn(BaseModel):
    key: str = Field(..., min_length=1)


class ConfirmOut(BaseModel):
    media_id: str
    status: str
    storage_path: str | None = None
    format_detected: str | None = None


@router.post(
    "/projects/{project_id}/media/upload-url",
    response_model=UploadUrlOut,
    status_code=http_status.HTTP_201_CREATED,
)
def upload_url(
    project_id: uuid.UUID,
    data: UploadUrlIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = uuid.UUID(payload.get("sub"))
    project_check = db.query(Project).filter(Project.id == project_id).first()
    if not project_check:
        raise HTTPException(
            status_code=404, detail="Projet non trouvé ou accès refusé"
        )
    from app.models import StudioMembership

    user_studio_ids = [
        m.studio_id
        for m in db.query(StudioMembership)
        .filter(StudioMembership.user_id == user_id)
        .all()
    ]
    if user_studio_ids and project_check.studio_id not in user_studio_ids:
        raise HTTPException(
            status_code=404, detail="Projet non trouvé ou accès refusé"
        )
    media_id = uuid.uuid4()
    media = MediaAsset(
        id=media_id,
        project_id=project_id,
        storage_path=f"projects/{project_id}/media/{media_id}/{data.filename}",
        status="pending",
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    key = media.storage_path
    upload_url = generate_upload_url(
        key, content_type=data.content_type, expires_in=600
    )
    return UploadUrlOut(
        upload_url=upload_url, media_id=str(media.id), key=key, expires_in=600
    )


@router.post("/media/{media_id}/confirm", response_model=ConfirmOut)
def confirm_media(
    media_id: uuid.UUID,
    data: ConfirmIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    media = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Media introuvable")

    if (
        ".." in data.key
        or data.key.startswith("/")
        or "://" in data.key
        or "http:" in data.key
        or "file:" in data.key
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid storage key: path traversal or SSRF attempt blocked (§15.7)",
        )

    s3 = get_s3_client()
    settings = get_settings()
    tmp_path = f"/tmp/media_confirm_{media_id}.tmp"
    try:
        s3.download_file(settings.S3_BUCKET, data.key, tmp_path)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Échec téléchargement S3 : {exc}"
        )

    format_detected = _detect_format(tmp_path)
    is_valid = any(frag in format_detected for frag in ALLOWED_FORMAT_FRAGMENTS)
    if not is_valid:
        try:
            import os

            os.remove(tmp_path)
        except Exception:
            pass
        raise HTTPException(
            status_code=422,
            detail=f"Format non supporté: {format_detected} (attendus: MP4, MOV, MXF, AVI, MKV) — US-004",
        )

    media.status = "confirmed"
    media.storage_path = data.key
    db.commit()
    db.refresh(media)

    try:
        import os

        os.remove(tmp_path)
    except Exception:
        pass

    return ConfirmOut(
        media_id=str(media.id),
        status=media.status,
        storage_path=media.storage_path,
        format_detected=format_detected,
    )
