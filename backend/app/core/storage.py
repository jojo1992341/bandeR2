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


def ensure_bucket_encryption(
    bucket_name: str, s3_client=None, enabled: bool = True
):
    """Enforce AES-256 Server-Side Encryption at Rest on S3 bucket (§15.4)"""
    s3 = s3_client or get_s3_client()
    if not enabled:
        try:
            s3.delete_bucket_encryption(Bucket=bucket_name)
        except Exception:
            pass
        return
    try:
        s3.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "AES256"
                        }
                    }
                ]
            },
        )
    except Exception:
        pass


def upload_file_encrypted(
    local_path: str,
    bucket: str,
    key: str,
    aes256_enabled: bool = True,
    s3_client=None,
):
    """Upload object with SSE-S3 AES-256 at rest encryption (§15.4)"""
    s3 = s3_client or get_s3_client()
    extra_args = {"ServerSideEncryption": "AES256"} if aes256_enabled else {}
    s3.upload_file(local_path, bucket, key, ExtraArgs=extra_args)


def generate_upload_url(
    key: str,
    content_type: str = "video/mp4",
    expires_in: int = 600,
    aes256_enabled: bool = False,
) -> str:
    s3 = get_s3_client()
    settings = get_settings()
    try:
        s3.create_bucket(Bucket=settings.S3_BUCKET)
    except Exception:
        pass
    ensure_bucket_encryption(settings.S3_BUCKET, s3, enabled=True)
    params = {
        "Bucket": settings.S3_BUCKET,
        "Key": key,
        "ContentType": content_type,
    }
    if aes256_enabled:
        params["ServerSideEncryption"] = "AES256"
    url = s3.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=expires_in,
    )
    return url
