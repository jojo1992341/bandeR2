"""
Service de Stockage Objet pour RythmoAI (§12.2, §5.4 CDC)

Fournit une interface unifiée pour le stockage d'objets (S3/MinIO).
Utilisé par les workers IA pour lire/écrire des artefacts sans accès DB direct.
"""

from __future__ import annotations

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from typing import Any, Optional

from app.core.config import get_settings


class StorageService:
    """
    Service de stockage objet pour les workers et l'API.
    
    Permet:
    - Upload/download de fichiers
    - Stockage de métadonnées JSON
    - Gestion des buckets
    
    Conçu pour être utilisé par les workers sans accès DB.
    """
    
    def __init__(self, settings: Optional[Any] = None):
        """
        Initialise le service de stockage.
        
        Args:
            settings: Configuration (injection pour les tests)
        """
        self._settings = settings or get_settings()
        self._client = None
    
    @property
    def client(self) -> Any:
        """Retourne le client S3 (lazy initialization)."""
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._settings.S3_ENDPOINT_URL,
                aws_access_key_id=self._settings.S3_ACCESS_KEY,
                aws_secret_access_key=self._settings.S3_SECRET_KEY,
                config=Config(signature_version="s3v4"),
            )
        return self._client
    
    def ensure_bucket(self, bucket_name: Optional[str] = None) -> bool:
        """
        S'assure que le bucket existe.
        
        Args:
            bucket_name: Nom du bucket (défaut: S3_BUCKET)
            
        Returns:
            True si le bucket est prêt.
        """
        bucket = bucket_name or self._settings.S3_BUCKET
        try:
            self.client.create_bucket(Bucket=bucket)
        except ClientError as e:
            # Bucket existe déjà ou autre erreur
            if e.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                pass
        except Exception:
            pass
        return True
    
    def put_object(
        self,
        bucket: str,
        key: str,
        data: Any,
        content_type: str = "application/octet-stream"
    ) -> bool:
        """
        Stocke un objet dans le bucket.
        
        Args:
            bucket: Nom du bucket.
            key: Clé de l'objet.
            data: Données (str, bytes, dict, list).
            content_type: Type de contenu MIME.
            
        Returns:
            True si l'opération a réussi.
        """
        try:
            # Convertir les données en bytes
            if isinstance(data, str):
                data = data.encode("utf-8")
            elif isinstance(data, (dict, list)):
                import json
                data = json.dumps(data).encode("utf-8")
            elif not isinstance(data, bytes):
                data = str(data).encode("utf-8")
            
            self.ensure_bucket(bucket)
            self.client.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            return True
        except Exception:
            return False
    
    def get_object(self, bucket: str, key: str) -> Optional[Any]:
        """
        Récupère un objet du bucket.
        
        Args:
            bucket: Nom du bucket.
            key: Clé de l'objet.
            
        Returns:
            Données de l'objet ou None si introuvable.
        """
        try:
            response = self.client.get_object(Bucket=bucket, Key=key)
            body = response["Body"].read()
            
            # Tenter de décoder comme JSON
            try:
                import json
                return json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return body
        except ClientError:
            return None
        except Exception:
            return None
    
    def delete_object(self, bucket: str, key: str) -> bool:
        """
        Supprime un objet du bucket.
        
        Args:
            bucket: Nom du bucket.
            key: Clé de l'objet.
            
        Returns:
            True si l'opération a réussi.
        """
        try:
            self.client.delete_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False
    
    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        max_keys: int = 100
    ) -> list[dict]:
        """
        Liste les objets d'un bucket avec un préfixe.
        
        Args:
            bucket: Nom du bucket.
            prefix: Préfixe pour filtrer.
            max_keys: Nombre maximum de clés à retourner.
            
        Returns:
            Liste de dictionnaires avec 'Key' et 'LastModified'.
        """
        try:
            response = self.client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=max_keys
            )
            return response.get("Contents", [])
        except Exception:
            return []
    
    def generate_presigned_url(
        self,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
        expires_in: int = 3600
    ) -> Optional[str]:
        """
        Génère une URL pré-signée pour l'upload/download.
        
        Args:
            bucket: Nom du bucket.
            key: Clé de l'objet.
            content_type: Type de contenu.
            expires_in: Durée d'expiration en secondes.
            
        Returns:
            URL pré-signée ou None.
        """
        try:
            url = self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                    "ResponseContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
            return url
        except Exception:
            return None
    
    def upload_file(self, local_path: str, bucket: str, key: str) -> bool:
        """
        Upload un fichier depuis le système de fichiers.
        
        Args:
            local_path: Chemin local du fichier.
            bucket: Nom du bucket.
            key: Clé S3.
            
        Returns:
            True si l'upload a réussi.
        """
        try:
            self.ensure_bucket(bucket)
            self.client.upload_file(
                local_path,
                bucket,
                key,
                ExtraArgs={"ServerSideEncryption": "AES256"}
            )
            return True
        except Exception:
            return False
    
    def download_file(self, bucket: str, key: str, local_path: str) -> bool:
        """
        Télécharge un fichier vers le système de fichiers.
        
        Args:
            bucket: Nom du bucket.
            key: Clé S3.
            local_path: Chemin local de destination.
            
        Returns:
            True si le téléchargement a réussi.
        """
        try:
            self.client.download_file(bucket, key, local_path)
            return True
        except Exception:
            return False
    
    def health_check(self) -> dict:
        """
        Vérifie la santé du service de stockage.
        
        Returns:
            Dictionnaire de statut.
        """
        try:
            bucket = self._settings.S3_BUCKET
            self.client.head_bucket(Bucket=bucket)
            return {
                "status": "healthy",
                "bucket": bucket,
                "endpoint": self._settings.S3_ENDPOINT_URL,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }


def get_s3_client():
    """Retourne le client S3 (compatibilité ascendante)."""
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
    """Active le chiffrement AES-256 sur le bucket (§15.4)."""
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
    """Upload avec chiffrement SSE-S3 AES-256 (§15.4)."""
    s3 = s3_client or get_s3_client()
    extra_args = {"ServerSideEncryption": "AES256"} if aes256_enabled else {}
    s3.upload_file(local_path, bucket, key, ExtraArgs=extra_args)


def generate_upload_url(
    key: str,
    content_type: str = "video/mp4",
    expires_in: int = 600,
    aes256_enabled: bool = False,
) -> str:
    """Génère une URL pré-signée pour l'upload."""
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
