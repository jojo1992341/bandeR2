"""
Normalisation audio pour RythmoAI (§13.1 CDC)

Normalisation EBU R128 des fichiers audio.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from app.celery_app import celery_app  # Application Celery centralisée


def _ffmpeg_path() -> str:
    """Retourne le chemin vers ffmpeg."""
    p = shutil.which("ffmpeg")
    if p is None:
        for candidate in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
            if os.path.exists(candidate):
                return candidate
    return p or "ffmpeg"


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def normalize_audio(self, wav_path: str, output_path: str | None = None) -> dict[str, Any]:
    """
    Normalisation EBU R128 d'un fichier audio (§13.1).

    Args:
        wav_path: Chemin vers le fichier WAV à normaliser.
        output_path: Chemin de sortie (défaut: même nom avec suffixe _normalized).

    Returns:
        dict: Informations sur le fichier normalisé.
    """
    if output_path is None:
        output_path = wav_path.replace(".wav", "_normalized.wav")
    
    cmd = [
        _ffmpeg_path(),
        "-y",
        "-i",
        wav_path,
        "-af",
        "loudnorm=I=-23:TP=-2:LRA=11",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise self.retry(exc=RuntimeError(f"FFmpeg normalize failed: {result.stderr}"))
    
    return {"input": wav_path, "output": output_path, "status": "normalized_ebu_r128"}
