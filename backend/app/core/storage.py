import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from app.core.config import get_settings

def get_s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )

def generate_upload_url(key: str, content_type: str = "video/mp4", expires_in: int = 600) -> str:
    s3 = get_s3_client()
    settings = get_settings()
    url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.S3_BUCKET,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )
    return url
