"""
Adaptateur de Stockage S3 (§12.2, §6.2 CDC)

Implémente StoragePort en utilisant boto3 pour S3/MinIO.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.infrastructure.ports.storage import StoragePort


class S3StorageAdapter(StoragePort):
    """
    Adaptateur S3 utilisant boto3.
    
    Implémente StoragePort pour S3/MinIO.
    """
    
    def __init__(self, settings=None, s3_client=None):
        """
        Initialise l'adaptateur S3.
        
        Args:
            settings: Configuration (défaut: get_settings()).
            s3_client: Client S3 pré-construit (pour les tests).
        """
        self._settings = settings or get_settings()
        self._client = s3_client
        self._bucket = self._settings.S3_BUCKET
    
    @property
    def client(self):
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
        """S'assure que le bucket existe."""
        bucket = bucket_name or self._bucket
        try:
            self.client.create_bucket(Bucket=bucket)
        except ClientError as e:
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
        """Stocke un objet dans le bucket."""
        try:
            if isinstance(data, str):
                data = data.encode("utf-8")
            elif isinstance(data, (dict, list)):
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
        """Récupère un objet du bucket."""
        try:
            response = self.client.get_object(Bucket=bucket, Key=key)
            body = response["Body"].read()
            
            try:
                return json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return body
        except ClientError:
            return None
        except Exception:
            return None
    
    def delete_object(self, bucket: str, key: str) -> bool:
        """Supprime un objet du bucket."""
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
        """Liste les objets d'un bucket."""
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
        """Génère une URL pré-signée."""
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                    "ResponseContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
        except Exception:
            return None
    
    def upload_file(self, local_path: str, bucket: str, key: str) -> bool:
        """Upload un fichier depuis le système de fichiers."""
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
        """Télécharge un fichier vers le système de fichiers."""
        try:
            self.client.download_file(bucket, key, local_path)
            return True
        except Exception:
            return False
    
    def health_check(self) -> dict:
        """Vérifie la santé du service de stockage."""
        try:
            self.client.head_bucket(Bucket=self._bucket)
            return {
                "status": "healthy",
                "bucket": self._bucket,
                "endpoint": self._settings.S3_ENDPOINT_URL,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }


class MemoryStorageAdapter(StoragePort):
    """
    Adaptateur de stockage en mémoire (pour les tests).
    
    Implémente StoragePort en utilisant un dictionnaire.
    """
    
    def __init__(self):
        """Initialise le stockage mémoire."""
        self._storage: dict[str, bytes] = {}
    
    def ensure_bucket(self, bucket_name: Optional[str] = None) -> bool:
        """S'assure que le bucket existe (no-op pour mémoire)."""
        return True
    
    def put_object(
        self,
        bucket: str,
        key: str,
        data: Any,
        content_type: str = "application/octet-stream"
    ) -> bool:
        """Stocke un objet en mémoire."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        elif isinstance(data, (dict, list)):
            import json
            data = json.dumps(data).encode("utf-8")
        elif not isinstance(data, bytes):
            data = str(data).encode("utf-8")
        
        full_key = f"{bucket}/{key}" if bucket else key
        self._storage[full_key] = data
        return True
    
    def get_object(self, bucket: str, key: str) -> Optional[Any]:
        """Récupère un objet de la mémoire."""
        full_key = f"{bucket}/{key}" if bucket else key
        
        if full_key not in self._storage:
            return None
        
        data = self._storage[full_key]
        
        # Tenter de décoder comme JSON
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return data
    
    def delete_object(self, bucket: str, key: str) -> bool:
        """Supprime un objet de la mémoire."""
        full_key = f"{bucket}/{key}" if bucket else key
        
        if full_key in self._storage:
            del self._storage[full_key]
            return True
        return False
    
    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        max_keys: int = 100
    ) -> list[dict]:
        """Liste les objets en mémoire."""
        results = []
        count = 0
        
        # Construire le préfixe complet
        full_prefix = f"{bucket}/{prefix}" if bucket else prefix
        
        for key in self._storage.keys():
            if key.startswith(full_prefix):
                results.append({
                    "Key": key,
                    "LastModified": "2024-01-01T00:00:00Z",
                })
                count += 1
                if count >= max_keys:
                    break
        
        return results
    
    def generate_presigned_url(
        self,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
        expires_in: int = 3600
    ) -> Optional[str]:
        """Génère une URL factice pour les tests."""
        return f"memory://{bucket}/{key}"
    
    def upload_file(self, local_path: str, bucket: str, key: str) -> bool:
        """Simule un upload de fichier."""
        try:
            with open(local_path, "rb") as f:
                content = f.read()
            return self.put_object(bucket, key, content)
        except Exception:
            return False
    
    def download_file(self, bucket: str, key: str, local_path: str) -> bool:
        """Simule un download de fichier."""
        try:
            data = self.get_object(bucket, key)
            if data is None:
                return False
            
            if isinstance(data, bytes):
                with open(local_path, "wb") as f:
                    f.write(data)
            else:
                with open(local_path, "w") as f:
                    f.write(str(data))
            return True
        except Exception:
            return False
    
    def health_check(self) -> dict:
        """Vérifie la santé du stockage mémoire."""
        return {
            "status": "healthy",
            "storage_type": "memory",
            "object_count": len(self._storage),
        }
