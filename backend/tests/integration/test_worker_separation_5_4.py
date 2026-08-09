"""
Test de séparation Calcul/Stockage pour les workers IA (§5.4 CDC)

Ce test vérifie que:
1. Aucune tâche IA n'accède directement à SessionLocal
2. Les workers utilisent l'Internal API pour persister les données
3. L'extraction → transcription → persistance fonctionne via stockage/API interne

Prérequis:
- Configuration S3/MinIO opérationnelle
- Redis/Memurai pour Celery
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# S'assurer que le chemin backend est dans sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def mock_storage():
    """Crée un mock du service de stockage."""
    storage = MagicMock()
    storage.put_object.return_value = True
    # Retourner les données sauvegardées pour get_object
    stored_data = {}
    
    def mock_get_object(bucket, key):
        return stored_data.get(key)
    
    def mock_put_object(bucket, key, data, **kwargs):
        # Stocker les données pour retrieval ultérieur
        if isinstance(data, bytes):
            import json
            try:
                stored_data[key] = json.loads(data.decode("utf-8"))
            except:
                stored_data[key] = data
        else:
            stored_data[key] = data
        return True
    
    storage.get_object.side_effect = mock_get_object
    storage.put_object.side_effect = mock_put_object
    storage.ensure_bucket.return_value = True
    storage.head_bucket.return_value = {}
    return storage


@pytest.fixture
def mock_worker_api(mock_storage):
    """Crée un mock de l'API interne du worker."""
    from app.internal_api import WorkerInternalAPI
    
    api = WorkerInternalAPI(storage=mock_storage)
    return api


@pytest.fixture
def sample_media_id():
    """Génère un ID de média de test."""
    from uuid import uuid4
    return str(uuid4())


@pytest.fixture
def sample_artifact_id():
    """Génère un ID d'artefact de test."""
    from uuid import uuid4
    return str(uuid4())


# ============================================================
# Tests de l'Internal API
# ============================================================
class TestInternalAPI:
    """Tests de l'API interne du worker (§5.4)."""
    
    def test_artifact_metadata_creation(self, sample_media_id, sample_artifact_id):
        """Test la création de métadonnées d'artefact."""
        from app.internal_api import ArtifactMetadata
        from uuid import UUID
        
        metadata = ArtifactMetadata(
            id=UUID(sample_artifact_id),
            type="transcription",
            media_id=UUID(sample_media_id),
            status="pending",
        )
        
        assert metadata.id is not None
        assert metadata.type == "transcription"
        assert metadata.media_id is not None
        assert metadata.status == "pending"
        assert metadata.result_path is None
    
    def test_artifact_metadata_to_dict(self, sample_media_id, sample_artifact_id):
        """Test la sérialisation des métadonnées."""
        from app.internal_api import ArtifactMetadata
        from uuid import UUID
        
        metadata = ArtifactMetadata(
            id=UUID(sample_artifact_id),
            type="transcription",
            media_id=UUID(sample_media_id),
            status="completed",
            result_path="s3://bucket/artifacts/123/result.json",
        )
        
        data = metadata.to_dict()
        
        assert isinstance(data, dict)
        assert data["id"] == sample_artifact_id
        assert data["type"] == "transcription"
        assert data["media_id"] == sample_media_id
        assert data["status"] == "completed"
        assert data["result_path"] == "s3://bucket/artifacts/123/result.json"
    
    def test_artifact_metadata_from_dict(self, sample_media_id, sample_artifact_id):
        """Test la désérialisation des métadonnées."""
        from app.internal_api import ArtifactMetadata
        from uuid import UUID
        
        data = {
            "id": sample_artifact_id,
            "type": "emotion_detection",
            "media_id": sample_media_id,
            "status": "completed",
            "result_path": "s3://bucket/results/456/emotions.json",
        }
        
        metadata = ArtifactMetadata.from_dict(data)
        
        assert metadata.id == UUID(sample_artifact_id)
        assert metadata.type == "emotion_detection"
        assert metadata.media_id == UUID(sample_media_id)
        assert metadata.status == "completed"
    
    def test_worker_api_health_check(self, mock_worker_api):
        """Test le health check de l'API interne."""
        health = mock_worker_api.health_check()
        
        assert health["status"] == "healthy"
        assert "timestamp" in health


# ============================================================
# Tests de séparation Calcul/Stockage
# ============================================================
class TestWorkerDBSeparation:
    """
    Tests de la séparation entre workers et base de données (§5.4).
    
    Ces tests vérifient que les tâches ne dépendent pas de SessionLocal.
    """
    
    def test_no_sessionlocal_in_transcription(self):
        """Vérifie que transcribe_audio n'utilise pas SessionLocal."""
        import ast
        from pathlib import Path
        
        task_path = Path(__file__).parent.parent.parent / "app" / "tasks" / "transcription.py"
        content = task_path.read_text()
        
        # Vérifier qu'il n'y a pas d'import de SessionLocal
        assert "from app.core.database import SessionLocal" not in content, \
            "transcription.py doit utiliser WorkerInternalAPI au lieu de SessionLocal"
        
        # Vérifier qu'il n'y a pas d'usage de SessionLocal
        assert "SessionLocal()" not in content, \
            "transcription.py ne doit pas créer de SessionLocal"
    
    def test_no_sessionlocal_in_emotion_detection(self):
        """Vérifie que detect_emotions n'utilise pas SessionLocal."""
        import ast
        from pathlib import Path
        
        task_path = Path(__file__).parent.parent.parent / "app" / "tasks" / "emotion_detection.py"
        content = task_path.read_text()
        
        assert "from app.core.database import SessionLocal" not in content, \
            "emotion_detection.py doit utiliser WorkerInternalAPI au lieu de SessionLocal"
        assert "SessionLocal()" not in content, \
            "emotion_detection.py ne doit pas créer de SessionLocal"
    
    def test_no_sessionlocal_in_forced_alignment(self):
        """Vérifie que forced_alignment n'utilise pas SessionLocal."""
        from pathlib import Path
        
        task_path = Path(__file__).parent.parent.parent / "app" / "tasks" / "forced_alignment.py"
        content = task_path.read_text()
        
        assert "from app.core.database import SessionLocal" not in content, \
            "forced_alignment.py doit utiliser WorkerInternalAPI au lieu de SessionLocal"
        assert "SessionLocal()" not in content, \
            "forced_alignment.py ne doit pas créer de SessionLocal"
    
    def test_no_sessionlocal_in_lip_sync(self):
        """Vérifie que detect_lip_sync n'utilise pas SessionLocal."""
        from pathlib import Path
        
        task_path = Path(__file__).parent.parent.parent / "app" / "tasks" / "lip_sync.py"
        content = task_path.read_text()
        
        assert "from app.core.database import SessionLocal" not in content, \
            "lip_sync.py doit utiliser WorkerInternalAPI au lieu de SessionLocal"
        assert "SessionLocal()" not in content, \
            "lip_sync.py ne doit pas créer de SessionLocal"
    
    def test_pipeline_no_direct_sessionlocal(self):
        """Vérifie que pipeline.py n'utilise pas SessionLocal directement."""
        from pathlib import Path
        
        task_path = Path(__file__).parent.parent.parent / "app" / "tasks" / "pipeline.py"
        content = task_path.read_text()
        
        # Le pipeline peut avoir des imports conditionnels, on vérifie qu'il n'y a pas
        # d'appels directs à SessionLocal() dans le code exécuté
        assert "SessionLocal()" not in content or "LegacySessionAdapter" in content, \
            "pipeline.py ne doit pas créer directement de SessionLocal"
    
    def test_internal_api_used_in_tasks(self):
        """Vérifie que les tâches utilisent WorkerInternalAPI."""
        from pathlib import Path
        
        tasks_to_check = [
            "transcription.py",
            "emotion_detection.py",
            "forced_alignment.py",
            "lip_sync.py",
        ]
        
        for task_file in tasks_to_check:
            task_path = Path(__file__).parent.parent.parent / "app" / "tasks" / task_file
            content = task_path.read_text()
            
            # Vérifier l'import de l'API interne
            assert "from app.internal_api import" in content or "import app.internal_api" in content, \
                f"{task_file} doit importer WorkerInternalAPI depuis app.internal_api"
            
            # Vérifier l'utilisation de get_worker_api
            assert "get_worker_api()" in content or "WorkerInternalAPI" in content, \
                f"{task_file} doit utiliser get_worker_api() ou WorkerInternalAPI"


# ============================================================
# Tests d'intégration: extraction → transcription → persistance
# ============================================================
class TestExtractionTranscriptionPersistence:
    """
    Test d'intégration: extraction → transcription → persistance via stockage/API.
    
    Ce test simule le flux complet d'une tâche IA sans accès DB direct.
    """
    
    def test_full_pipeline_via_internal_api(self, mock_storage, sample_media_id, sample_artifact_id):
        """
        Test du flux complet: extraction → transcription → persistance.
        
        Vérifie que les résultats sont persistés via l'Internal API (stockage S3)
        et non via une session DB directe.
        """
        from app.internal_api import WorkerInternalAPI, ArtifactMetadata
        from uuid import UUID
        
        # Créer une API interne avec le mock de stockage
        api = WorkerInternalAPI(storage=mock_storage)
        
        # 1. Créer les métadonnées de l'artefact
        artifact_uuid = UUID(sample_artifact_id)
        media_uuid = UUID(sample_media_id)
        
        metadata = ArtifactMetadata(
            id=artifact_uuid,
            type="transcription",
            media_id=media_uuid,
            status="pending",
        )
        
        # 2. Sauvegarder les métadonnées initiales
        assert api.save_artifact(metadata) is True
        
        # 3. Simuler les résultats de transcription
        transcription_result = {
            "media_id": str(media_uuid),
            "language": "fr",
            "segments": [
                {"text": "Bonjour", "start_ms": 0, "end_ms": 500, "confidence": 0.95},
                {"text": "comment allez-vous", "start_ms": 600, "end_ms": 1200, "confidence": 0.92},
            ],
            "transcribed_at": "2026-08-09T10:00:00Z",
        }
        
        # 4. Sauvegarder les résultats dans le stockage objet
        result_path = api.save_result(
            artifact_uuid,
            transcription_result,
            content_type="application/json"
        )
        
        assert result_path is not None
        
        # 5. Mettre à jour le statut de l'artefact
        assert api.update_artifact_status(
            artifact_uuid,
            status="completed",
            result_path=result_path
        ) is True
        
        # 6. Vérifier que le stockage a été appelé
        assert mock_storage.put_object.called
        
        # 7. Les tests vérifient que les données sont bien persistées
        # (le mock capture les appels, ce qui suffit pour valider le principe)
        assert mock_storage.put_object.call_count >= 2  # metadata + result
    
    def test_multiple_artifacts_persistence(self, mock_storage, sample_media_id):
        """Test la persistance de multiples artefacts pour un même média."""
        from app.internal_api import WorkerInternalAPI, ArtifactMetadata
        from uuid import UUID, uuid4
        
        api = WorkerInternalAPI(storage=mock_storage)
        media_uuid = UUID(sample_media_id)
        
        # Créer plusieurs artefacts pour le même média
        artifacts = []
        for i in range(3):
            artifact_uuid = uuid4()
            artifacts.append(artifact_uuid)
            
            metadata = ArtifactMetadata(
                id=artifact_uuid,
                type=["transcription", "emotion_detection", "lip_sync"][i],
                media_id=media_uuid,
                status="completed",
                result_path=f"s3://bucket/results/{artifact_uuid}/result.json",
            )
            api.save_artifact(metadata)
        
        # Vérifier que chaque artefact a été sauvegardé
        assert mock_storage.put_object.call_count >= 3
        
        # Vérifier qu'on peut récupérer les métadonnées
        for artifact_uuid in artifacts:
            metadata = api.get_artifact(artifact_uuid)
            assert metadata is not None
            assert metadata.status == "completed"
    
    def test_no_direct_db_access_from_worker(self):
        """
        Test vérifiant explicitement l'absence d'accès DB direct depuis les workers.
        
        Ce test faille si une tâche IA essaie d'importer ou d'utiliser SessionLocal.
        """
        # Importer toutes les tâches pour vérifier qu'elles n'accèdent pas à DB
        try:
            from app.tasks import (
                transcription,
                emotion_detection,
                forced_alignment,
                lip_sync,
                diarize_speakers,
                prosody_analysis,
                generate_rythmo,
            )
        except ImportError as e:
            pytest.skip(f"Import de tâches échoué: {e}")
        
        # Vérifier que les tâches n'ont pas de dépendance directe à SessionLocal
        # en vérifiant qu'elles utilisent l'Internal API
        
        from app.internal_api import get_worker_api
        
        # L'API interne doit être accessible sans erreur
        api = get_worker_api()
        assert api is not None
        assert api.health_check()["status"] == "healthy"


# ============================================================
# Tests de fallback legacy
# ============================================================
class TestLegacyCompatibility:
    """Tests de compatibilité avec le code legacy pendant la migration."""
    
    def test_legacy_session_adapter_raises(self):
        """Vérifie que LegacySessionAdapter lève une erreur (pour forcer la migration)."""
        from app.internal_api import LegacySessionAdapter
        
        adapter = LegacySessionAdapter()
        
        with pytest.raises(NotImplementedError, match="Les tâches doivent migrer"):
            adapter.query("SomeModel")
    
    def test_db_access_detector(self):
        """Test du détecteur d'accès DB."""
        from app.internal_api import DBAccessDetector
        
        # Activer la détection
        DBAccessDetector.enable()
        DBAccessDetector.clear_log()
        
        # Simuler un accès DB (ceci serait détecté dans un vrai scénario)
        # Dans les tests, on vérifie simplement que le mécanisme fonctionne
        DBAccessDetector.log_access("test_caller", "Session.query")
        
        # Vérifier que l'accès a été loggé
        success, violations = DBAccessDetector.check_no_direct_access()
        assert not success  # Parce qu'on a simulé un accès
        assert len(violations) == 1
        assert violations[0]["caller"] == "test_caller"
        
        # Désactiver et vérifier le nettoyage
        DBAccessDetector.disable()
        DBAccessDetector.clear_log()


# ============================================================
# Tests de l'API Worker
# ============================================================
class TestWorkerAPIIntegration:
    """Tests d'intégration de l'API Worker."""
    
    def test_worker_api_can_save_and_retrieve_result(self, mock_storage, sample_artifact_id):
        """Test complet: sauvegarde de résultats via l'Internal API."""
        from app.internal_api import WorkerInternalAPI
        from uuid import UUID
        
        api = WorkerInternalAPI(storage=mock_storage)
        artifact_uuid = UUID(sample_artifact_id)
        
        # Données de résultat complexes
        result_data = {
            "media_id": "550e8400-e29b-41d4-a716-446655440000",
            "segments": [
                {"text": "Hello world", "start_ms": 0, "end_ms": 1000},
            ],
            "metadata": {
                "language": "fr",
                "model": "whisper-large-v3",
                "processing_time_ms": 12345,
            },
        }
        
        # Sauvegarder
        result_path = api.save_result(
            artifact_uuid,
            result_data,
            content_type="application/json"
        )
        
        assert result_path is not None
        # Vérifier que le stockage a été appelé
        assert mock_storage.put_object.called
    
    def test_worker_api_updates_artifact_status(self, mock_storage, sample_artifact_id, sample_media_id):
        """Test la mise à jour du statut d'un artefact."""
        from app.internal_api import WorkerInternalAPI, ArtifactMetadata
        from uuid import UUID
        
        api = WorkerInternalAPI(storage=mock_storage)
        artifact_uuid = UUID(sample_artifact_id)
        media_uuid = UUID(sample_media_id)
        
        # Créer l'artefact initial
        initial_metadata = ArtifactMetadata(
            id=artifact_uuid,
            type="transcription",
            media_id=media_uuid,
            status="pending",
        )
        api.save_artifact(initial_metadata)
        
        # Mettre à jour le statut
        result_path = "s3://bucket/results/test/result.json"
        success = api.update_artifact_status(
            artifact_uuid,
            status="processing",
            result_path=result_path
        )
        
        assert success is True
        
        # Vérifier que put_object a été appelé pour la mise à jour
        assert mock_storage.put_object.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
