"""
Package de tâches Celery pour RythmoAI (§6.4, §13.1 CDC)

Ce module centralise l'accès à l'application Celery.

Utilisation:
    from app.tasks import celery_app
    from app.tasks.pipeline import pipeline_extract_normalize
    
    # Ou pour l'autodécouverte:
    from app.celery_app import celery_app
"""

# Réexporter l'application Celery centralisée
from app.celery_app import celery_app  # noqa: F401, E402

# Import des modules de tâches pour autodécouverte
# Ces imports permettent à Celery de trouver les tâches décorées
from app.tasks import (  # noqa: F401, E402
    pipeline,
    transcription,
    export,
    normalize_audio,
    forced_alignment,
    diarize_speakers,
    prosody_analysis,
    generate_rythmo,
    audio_extraction,
    lip_sync,
    source_separation,
    emotion_detection,
    rythmo_generation,
    diarization,
    prosody,
)

# Pour compatibilité ascendante - certains modules imports directement depuis pipeline
# Ces variables sont définies dans app.celery_app et réexportées
__all__ = [
    "celery_app",
    "pipeline",
    "transcription", 
    "export",
    "normalize_audio",
    "forced_alignment",
    "diarize_speakers",
    "prosody_analysis",
    "generate_rythmo",
    "audio_extraction",
    "lip_sync",
    "source_separation",
]
