"""
Port de Stockage (§12.2, §6.2 CDC)

Interface stable pour le stockage d'objets. Les adaptateurs (S3, MinIO, mémoire)
doivent implémenter cette interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class StoragePort(ABC):
    """
    Interface pour le stockage d'objets.
    
    Les implémentations peuvent utiliser S3, MinIO, ou un stockage en mémoire
    pour les tests.
    """
    
    @abstractmethod
    def ensure_bucket(self, bucket_name: Optional[str] = None) -> bool:
        """
        S'assure que le bucket existe.
        
        Args:
            bucket_name: Nom du bucket (défaut: bucket configuré).
            
        Returns:
            True si le bucket est prêt.
        """
        ...
    
    @abstractmethod
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
        ...
    
    @abstractmethod
    def get_object(self, bucket: str, key: str) -> Optional[Any]:
        """
        Récupère un objet du bucket.
        
        Args:
            bucket: Nom du bucket.
            key: Clé de l'objet.
            
        Returns:
            Données de l'objet ou None si introuvable.
        """
        ...
    
    @abstractmethod
    def delete_object(self, bucket: str, key: str) -> bool:
        """
        Supprime un objet du bucket.
        
        Args:
            bucket: Nom du bucket.
            key: Clé de l'objet.
            
        Returns:
            True si l'opération a réussi.
        """
        ...
    
    @abstractmethod
    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        max_keys: int = 100
    ) -> list[dict]:
        """
        Liste les objets d'un bucket.
        
        Args:
            bucket: Nom du bucket.
            prefix: Préfixe pour filtrer.
            max_keys: Nombre maximum de clés.
            
        Returns:
            Liste de dictionnaires avec 'Key' et 'LastModified'.
        """
        ...
    
    @abstractmethod
    def generate_presigned_url(
        self,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
        expires_in: int = 3600
    ) -> Optional[str]:
        """
        Génère une URL pré-signée.
        
        Args:
            bucket: Nom du bucket.
            key: Clé de l'objet.
            content_type: Type de contenu.
            expires_in: Durée d'expiration en secondes.
            
        Returns:
            URL pré-signée ou None.
        """
        ...
    
    @abstractmethod
    def upload_file(self, local_path: str, bucket: str, key: str) -> bool:
        """
        Upload un fichier depuis le système de fichiers.
        
        Args:
            local_path: Chemin local.
            bucket: Nom du bucket.
            key: Clé S3.
            
        Returns:
            True si l'upload a réussi.
        """
        ...
    
    @abstractmethod
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
        ...
    
    @abstractmethod
    def health_check(self) -> dict:
        """
        Vérifie la santé du service de stockage.
        
        Returns:
            Dictionnaire avec le statut.
        """
        ...
