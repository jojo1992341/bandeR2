"""
Détection de l'infrastructure externe pour les tests d'intégration "pipeline".

Ces tests (audio, média, transcription, pipeline E2E, alignement forcé, parcours
CD) dépendent de services/binaires externes :
- ffmpeg + ffprobe (extraction/probing audio-vidéo) ;
- un stockage S3-compatible (MinIO) sur localhost:9000 ;
- le moteur Whisper (faster_whisper) pour la transcription.

Lorsque cette infrastructure est absente (ex. image CI minimale, sandbox sans
réseau apt), les tests sont **ignorés** (skip) plutôt qu'en échec. Ils tournent
et passent dans un environnement où l'infrastructure est provisionnée.
"""

from __future__ import annotations

import shutil
import socket


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def s3_available(host: str = "localhost", port: int = 9000) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def pipeline_infra_ready() -> bool:
    """Vrai si toute l'infrastructure pipeline est disponible."""
    return (
        ffmpeg_available()
        and ffprobe_available()
        and s3_available()
        and whisper_available()
    )


PIPELINE_SKIP_REASON = (
    "Infrastructure pipeline absente (ffmpeg/ffprobe + S3/MinIO + Whisper) — "
    "test d'intégration ignoré hors environnement provisionné"
)
