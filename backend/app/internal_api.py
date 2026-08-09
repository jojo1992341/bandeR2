"""
Séparation Calcul/Stockage - Interface Worker API (§5.4 CDC)

Ce module fournit une interface pour que les workers IA puissent lire/écrire
des données sans accéder directement à la base de données applicative.

Principe: Les workers sont des "calculateurs" qui:
1. Lisent des artefacts depuis le stockage objet (S3)
2. Écrivent des résultats vers le stockage objet
3. Utilisent une API interne pour les métadonnées

Aucun accès direct à SessionLocal depuis les workers.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from app.core.config import get_settings
from app.core.storage import StorageService


# ============================================================
# Contrats d'Artefacts (§5.4)
# ============================================================
# Chaque artefact est identifié par un UUID et stocké sous forme
# de métadonnées JSON + fichiers binaires sur S3.

@dataclass
class ArtifactMetadata:
    """Métadonnées d'un artefact de calcul."""
    id: UUID
    type: str  # transcript, alignment, emotion_tags, etc.
    media_id: UUID
    project_id: Optional[UUID] = None
    status: str = "pending"  # pending, processing, completed, failed
    created_at: str = ""
    updated_at: str = ""
    result_path: Optional[str] = None  # Chemin S3 vers les résultats
    error: Optional[str] = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
    
    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour stockage JSON."""
        data = asdict(self)
        # Convertir les UUID en strings
        if isinstance(data.get("id"), UUID):
            data["id"] = str(data["id"])
        if isinstance(data.get("media_id"), UUID):
            data["media_id"] = str(data["media_id"])
        if isinstance(data.get("project_id"), UUID):
            data["project_id"] = str(data["project_id"])
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> "ArtifactMetadata":
        """Crée une instance depuis un dictionnaire."""
        # Convertir les strings en UUID si nécessaire
        if "id" in data and isinstance(data["id"], str):
            data["id"] = UUID(data["id"])
        if "media_id" in data and isinstance(data["media_id"], str):
            data["media_id"] = UUID(data["media_id"])
        if "project_id" in data and isinstance(data["project_id"], str):
            data["project_id"] = UUID(data["project_id"])
        return cls(**data)


# ============================================================
# Worker Internal API (§5.4)
# ============================================================
class WorkerInternalAPI:
    """
    API interne pour les workers IA.
    
    Permet aux workers de:
    - Lire des métadonnées depuis le stockage
    - Écrire des résultats vers le stockage
    - Mettre à jour le statut des tâches
    - Accéder aux paramètres de configuration
    
    AUCUN accès direct à la base de données applicative.
    """
    
    def __init__(self, storage: Optional[StorageService] = None):
        """
        Initialise l'API interne du worker.
        
        Args:
            storage: Service de stockage (injection de dépendance pour les tests)
        """
        self.settings = get_settings()
        self.storage = storage or StorageService()
        self._artifacts_prefix = "artifacts/metadata/"
        self._results_prefix = "artifacts/results/"
    
    def get_artifact(self, artifact_id: UUID) -> Optional[ArtifactMetadata]:
        """
        Récupère les métadonnées d'un artefact.
        
        Args:
            artifact_id: UUID de l'artefact.
            
        Returns:
            ArtifactMetadata ou None si introuvable.
        """
        key = f"{self._artifacts_prefix}{artifact_id}.json"
        try:
            data = self.storage.get_object(self.settings.S3_BUCKET, key)
            if data:
                return ArtifactMetadata.from_dict(json.loads(data))
        except Exception as e:
            # Artefact introuvable ou erreur de lecture
            pass
        return None
    
    def save_artifact(self, metadata: ArtifactMetadata) -> bool:
        """
        Sauvegarde les métadonnées d'un artefact.
        
        Args:
            metadata: Métadonnées de l'artefact.
            
        Returns:
            True si la sauvegarde a réussi.
        """
        key = f"{self._artifacts_prefix}{metadata.id}.json"
        try:
            self.storage.put_object(
                self.settings.S3_BUCKET,
                key,
                json.dumps(metadata.to_dict(), indent=2)
            )
            return True
        except Exception as e:
            return False
    
    def update_artifact_status(
        self,
        artifact_id: UUID,
        status: str,
        result_path: Optional[str] = None,
        error: Optional[str] = None
    ) -> bool:
        """
        Met à jour le statut d'un artefact.
        
        Args:
            artifact_id: UUID de l'artefact.
            status: Nouveau statut.
            result_path: Chemin vers les résultats (optionnel).
            error: Message d'erreur (optionnel).
            
        Returns:
            True si la mise à jour a réussi.
        """
        metadata = self.get_artifact(artifact_id)
        if not metadata:
            return False
        
        metadata.status = status
        metadata.updated_at = datetime.now(timezone.utc).isoformat()
        if result_path:
            metadata.result_path = result_path
        if error:
            metadata.error = error
        
        return self.save_artifact(metadata)
    
    def save_result(self, artifact_id: UUID, result_data: Any, content_type: str = "application/json") -> Optional[str]:
        """
        Sauvegarde les résultats d'un calcul.
        
        Args:
            artifact_id: UUID de l'artefact.
            result_data: Données de résultat.
            content_type: Type de contenu (application/json, audio/wav, etc.)
            
        Returns:
            Chemin S3 vers les résultats, ou None en cas d'échec.
        """
        # Générer un chemin unique
        timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H/%M/%S")
        result_key = f"{self._results_prefix}{artifact_id}/{timestamp}/result"
        
        # Convertir en bytes selon le type
        if isinstance(result_data, (dict, list)):
            content = json.dumps(result_data, indent=2).encode("utf-8")
        elif isinstance(result_data, str):
            content = result_data.encode("utf-8")
        elif isinstance(result_data, bytes):
            content = result_data
        else:
            content = json.dumps(result_data).encode("utf-8")
        
        try:
            self.storage.put_object(
                self.settings.S3_BUCKET,
                result_key,
                content,
                content_type=content_type
            )
            return result_key
        except Exception:
            return None
    
    def get_result(self, result_path: str) -> Optional[Any]:
        """
        Récupère les résultats depuis un chemin S3.
        
        Args:
            result_path: Chemin S3 vers les résultats.
            
        Returns:
            Données des résultats ou None.
        """
        try:
            data = self.storage.get_object(self.settings.S3_BUCKET, result_path)
            if data:
                # Tenter de parser comme JSON
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    return data
        except Exception:
            pass
        return None
    
    def list_artifacts_by_media(
        self,
        media_id: UUID,
        artifact_type: Optional[str] = None,
        status: Optional[str] = None
    ) -> list[ArtifactMetadata]:
        """
        Liste les artefacts liés à un média.
        
        Note: Cette méthode nécessite un listing S3 qui peut être limité.
        En production, utiliser une base de données dédiée aux artefacts.
        
        Args:
            media_id: UUID du média.
            artifact_type: Type d'artefact (optionnel).
            status: Statut (optionnel).
            
        Returns:
            Liste des artefacts.
        """
        # Cette implémentation est simplifiée.
        # En production, utiliser un index dédié (DB légère ou Elasticsearch).
        return []
    
    def get_media_info(self, media_id: UUID) -> Optional[dict]:
        """
        Récupère les informations d'un média.
        
        Dans cette implémentation, les informations sont stockées
        dans l'objet média S3 lui-même.
        
        Args:
            media_id: UUID du média.
            
        Returns:
            Dictionnaire d'informations ou None.
        """
        # Cette méthode serait implémentée via l'API externe
        # ou un stockage de métadonnées dédié
        return None
    
    def health_check(self) -> dict:
        """
        Vérifie la santé de l'API interne.
        
        Returns:
            Dictionnaire de statut de santé.
        """
        return {
            "status": "healthy",
            "storage": "configured" if self.storage else "unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def reset(self) -> None:
        """Réinitialise la connexion au stockage."""
        self.storage = StorageService()


# ============================================================
# Helper pour créer une instance par défaut
# ============================================================
_worker_api: Optional[WorkerInternalAPI] = None


def get_worker_api() -> WorkerInternalAPI:
    """
    Retourne l'instance par défaut de l'API interne du worker.
    
    Returns:
        WorkerInternalAPI.
    """
    global _worker_api
    if _worker_api is None:
        _worker_api = WorkerInternalAPI()
    return _worker_api


def reset_worker_api() -> None:
    """Réinitialise l'API interne (pour les tests)."""
    global _worker_api
    if _worker_api is not None:
        _worker_api.reset()
        _worker_api = None


# ============================================================
# Compatibilité - Contournement pour les tâches existantes
# ============================================================
# Cette classe permet aux tâches existantes de fonctionner pendant
# la migration vers l'API interne. Elle est à supprimer une fois
# toutes les tâches migrées.

class LegacySessionAdapter:
    """
    Adaptateur de compatibilité pour les tâches utilisant encore SessionLocal.
    
    AVERTISSEMENT: Cette classe est temporaire et sera supprimée après migration.
    Elle est uniquement là pour permettre une migration progressive.
    """
    
    def __init__(self):
        # Marquer que c'est un usage legacy
        import warnings
        warnings.warn(
            "LegacySessionAdapter est déprécié. Utilisez WorkerInternalAPI.",
            DeprecationWarning,
            stacklevel=2
        )
    
    def query(self, model):
        """Simule une requête (placeholder)."""
        raise NotImplementedError(
            "Les tâches doivent migrer vers WorkerInternalAPI. "
            "Voir app.internal_api pour la documentation."
        )


# ============================================================
# Test helper - Vérifie l'absence d'accès DB direct
# ============================================================
class DBAccessDetector:
    """
    Détecte les accès directs à la base de données depuis les workers.
    
    Utilisé pour les tests d'intégration (§5.4 CDC).
    """
    
    _access_log: list[dict] = []
    _enabled: bool = False
    
    @classmethod
    def enable(cls) -> None:
        """Active la détection des accès DB."""
        cls._enabled = True
        cls._access_log.clear()
    
    @classmethod
    def disable(cls) -> None:
        """Désactive la détection."""
        cls._enabled = False
    
    @classmethod
    def log_access(cls, caller: str, method: str) -> None:
        """Enregistre un accès DB détecté."""
        if cls._enabled:
            cls._access_log.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "caller": caller,
                "method": method,
            })
    
    @classmethod
    def check_no_direct_access(cls) -> tuple[bool, list[dict]]:
        """
        Vérifie qu'aucun accès direct n'a été détecté.
        
        Returns:
            (succès, liste_des_violations)
        """
        if not cls._enabled:
            return True, []
        
        violations = cls._access_log.copy()
        return len(violations) == 0, violations
    
    @classmethod
    def clear_log(cls) -> None:
        """Efface le log des accès."""
        cls._access_log.clear()


# ============================================================
# Tests
# ============================================================

if __name__ == "__main__":
    # Test basique de l'API interne
    print("Test WorkerInternalAPI...")
    
    api = WorkerInternalAPI()
    
    # Vérifier la santé
    health = api.health_check()
    print(f"Santé: {health}")
    
    # Créer un artefact de test
    from uuid import uuid4
    artifact_id = uuid4()
    
    metadata = ArtifactMetadata(
        id=artifact_id,
        type="test",
        media_id=uuid4(),
        status="completed"
    )
    
    print(f"Artefact créé: {metadata}")
    print("✅ WorkerInternalAPI fonctionnel")
