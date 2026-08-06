from minio import Minio
from minio.error import S3Error
import os
from datetime import timedelta
from typing import Optional

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "rythmoai-media")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

def ensure_bucket():
    """Create bucket if it doesn't exist."""
    try:
        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)
            print(f"✅ Created bucket: {MINIO_BUCKET}")
    except S3Error as e:
        print(f"MinIO error: {e}")

def get_presigned_upload_url(object_name: str, expires: int = 3600) -> str:
    """Generate pre-signed URL for upload (resumable)."""
    ensure_bucket()
    try:
        url = client.presigned_put_object(
            MINIO_BUCKET,
            object_name,
            expires=timedelta(seconds=expires)
        )
        return url
    except S3Error as e:
        raise Exception(f"Failed to generate upload URL: {e}")

def get_presigned_download_url(object_name: str, expires: int = 3600) -> str:
    """Generate pre-signed URL for download."""
    ensure_bucket()
    try:
        url = client.presigned_get_object(
            MINIO_BUCKET,
            object_name,
            expires=timedelta(seconds=expires)
        )
        return url
    except S3Error as e:
        raise Exception(f"Failed to generate download URL: {e}")

def upload_file(local_path: str, object_name: str):
    """Upload a file directly (for server-side use)."""
    ensure_bucket()
    client.fput_object(MINIO_BUCKET, object_name, local_path)
