"""
Application Celery centralisée pour RythmoAI (§6.4, §10.1 CDC)

Ce module fournit une instance Celery unique et configurée pour toute l'application.
Les tâches sont automatiquement découverts dans le package app.tasks.

Utilisation:
    from app.celery_app import celery_app
    
    @celery_app.task
    def ma_tache():
        pass

Lancement du worker:
    celery -A app.celery_app worker --loglevel=info
    
Inspecter les tâches:
    celery -A app.celery_app inspect registered
"""

from __future__ import annotations

import os
from typing import Any

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from app.core.config import get_settings


# ============================================================
# Configuration Celery
# ============================================================
def get_celery_config() -> dict[str, Any]:
    """
    Retourne la configuration Celery basée sur les paramètres de l'application.
    
    Returns:
        dict: Configuration Celery.
    """
    settings = get_settings()
    
    # Redis URL depuis la configuration (§10.1)
    redis_url = settings.REDIS_URL or "redis://localhost:6379/0"
    
    # Détecter si on est en mode test (variable d'environnement)
    is_test_mode = os.getenv("CELERY_TEST_MODE", "false").lower() in ("true", "1", "yes")
    
    config = {
        # Broker et backend (§6.4)
        "broker_url": redis_url,
        "result_backend": redis_url,
        
        # Sérialisation (§13.1)
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        "enable_utc": True,
        
        # Résilience et retry (§6.4 - retry 3, backoff exponentiel)
        "task_acks_late": True,
        "task_reject_on_worker_lost": True,
        "task_default_queue": "celery",
        "task_default_exchange": "celery",
        "task_default_routing_key": "celery",
        "task_default_delivery_mode": "persistent",
        
        # Retry configuration
        "task_max_retries": 3,
        "task_default_retry_delay": 10,
        "task_acks_on_failure_or_timeout": True,
        "task_timeout": 3600,  # 1 heure max par tâche
        "task_time_limit": 3300,  # 55 minutes (limite douce)
        "task_soft_time_limit": 3000,  # 50 minutes (interruption propre)
        
        # Workers (§18.3)
        "worker_prefetch_multiplier": 1,
        "worker_max_tasks_per_child": 1000,  # Rotatif après 1000 tâches
        "worker_max_memory_per_child": 500000,  # 500MB max par worker
        "worker_concurrency": 2,  # Concurrence par défaut (CPU-bound)
        
        # Autodécouverte des tâches
        "task_always_eager": is_test_mode,  # True en mode test, False en production
        "task_eager_propagates": True,
        
        # Monitoring et résultats
        "result_expires": 86400,  # 24 heures
        "result_persistent": True,
        "result_cache_max": 10000,
        
        # Dead Letter Queue (DLQ §6.4 / §10.3)
        "task_routes": {
            "app.tasks.pipeline.*": {"queue": "celery"},
            "app.tasks.dlq.*": {"queue": "dead_letter"},
            "app.tasks.export.*": {"queue": "exports"},
            "app.tasks.ia.*": {"queue": "ia"},
        },
        
        # Circuit breaker et monitoring
        "broker_transport_options": {
            "visibility_timeout": 3600,  # 1 heure
            "max_retries": 3,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 0.5,
        },
        
        # Debug et logging
        "worker_hijack_root_logger": False,
        "worker_redirect_stdouts": True,
        "worker_redirect_stdouts_level": "INFO",
    }
    
    return config


# ============================================================
# Application Celery unique
# ============================================================
celery_app = Celery("rythmoai")

# Charger la configuration
celery_app.config_from_object(get_celery_config())

# Découvrir automatiquement les tâches dans app.tasks
celery_app.autodiscover_tasks(["app.tasks"])

# Importer explicitement tous les modules de tâches pour garantir
# que toutes les tâches sont enregistrées (autodiscover n'est pas fiable)
import app.tasks.pipeline  # noqa: F401
import app.tasks.transcription  # noqa: F401
import app.tasks.export  # noqa: F401
import app.tasks.normalize_audio  # noqa: F401
import app.tasks.forced_alignment  # noqa: F401
import app.tasks.diarize_speakers  # noqa: F401
import app.tasks.prosody_analysis  # noqa: F401
import app.tasks.generate_rythmo  # noqa: F401
import app.tasks.audio_extraction  # noqa: F401
import app.tasks.lip_sync  # noqa: F401
import app.tasks.source_separation  # noqa: F401
import app.tasks.emotion_detection  # noqa: F401
import app.tasks.rythmo_generation  # noqa: F401
import app.tasks.diarization  # noqa: F401
import app.tasks.prosody  # noqa: F401
import app.tasks.export_project  # noqa: F401


# ============================================================
# Tâches de santé et monitoring
# ============================================================
@celery_app.task(name="app.tasks.health_check", bind=True, max_retries=0)
def health_check(self) -> dict[str, Any]:
    """
    Tâche de santé pour vérifier que Celery fonctionne correctement.
    
    Returns:
        dict: Status de santé avec métadonnées.
    """
    from datetime import datetime, timezone
    
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "worker": os.uname().nodename,
        "python_version": os.sys.version,
        "platform": os.uname().sysname,
    }


@celery_app.task(name="app.tasks.ping", bind=True, max_retries=0)
def ping(self) -> str:
    """
    Tâche ping simple pour tester la connectivité.
    
    Returns:
        str: "pong"
    """
    return "pong"


@celery_app.task(name="app.tasks.add", bind=True, max_retries=0)
def add(self, x: int, y: int) -> int:
    """
    Tâche simple pour additionner deux nombres (test).
    
    Args:
        x: Premier nombre.
        y: Deuxième nombre.
    
    Returns:
        int: Somme de x et y.
    """
    return x + y


# ============================================================
# Signaux worker (§6.4)
# ============================================================
@worker_process_init.connect
def configure_worker(**kwargs: Any) -> None:
    """
    Signal appelé lors de l'initialisation d'un worker.
    Utile pour configurer des ressources spécifiques au worker.
    """
    import logging
    logger = logging.getLogger("rythmoai.celery")
    logger.info("Worker Celery initialisé - PID: %s", os.getpid())


@worker_process_shutdown.connect
def shutdown_worker(**kwargs: Any) -> None:
    """
    Signal appelé lors de l'arrêt d'un worker.
    """
    import logging
    logger = logging.getLogger("rythmoai.celery")
    logger.info("Worker Celery arrêté - PID: %s", os.getpid())


# ============================================================
# Helpers pour les tâches
# ============================================================
def get_task_queue(task_name: str) -> str:
    """
    Détermine la queue pour une tâche donnée.
    
    Args:
        task_name: Nom de la tâche (ex: "app.tasks.pipeline.pipeline_extract_normalize")
    
    Returns:
        str: Nom de la queue.
    """
    if task_name.startswith("app.tasks.pipeline."):
        return "celery"
    elif task_name.startswith("app.tasks.dlq."):
        return "dead_letter"
    elif task_name.startswith("app.tasks.export."):
        return "exports"
    elif task_name.startswith("app.tasks.ia."):
        return "ia"
    else:
        return "celery"


def get_worker_count() -> int:
    """
    Retourne le nombre de workers recommandés basé sur les CPU disponibles.
    
    Returns:
        int: Nombre de workers.
    """
    import multiprocessing
    return max(1, multiprocessing.cpu_count())


# ============================================================
# Pour compatibilité avec le code existant
# ============================================================
# Certains modules imports directement celery_app depuis app.tasks.pipeline
# On exporte l'instance ici pour compatibilité

__all__ = [
    "celery_app",
    "health_check",
    "ping",
    "add",
    "get_celery_config",
    "get_task_queue",
    "get_worker_count",
]
