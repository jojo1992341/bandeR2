"""
Extraction audio pour RythmoAI (§11.2, §13.1 CDC)

Extraction des pistes audio multi-pistes depuis des fichiers vidéo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from typing import Any

import boto3

from app.celery_app import celery_app  # Application Celery centralisée
from app.core.config import get_settings


# Bucket de traitement (S3-compatible)
PROCESSING_BUCKET = "rythmoai-processing"


def _ffmpeg_path() -> str:
    """Retourne le chemin vers ffmpeg."""
    p = shutil.which("ffmpeg")
    if p is None:
        for candidate in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
            if os.path.exists(candidate):
                return candidate
    return p or "ffmpeg"


def _ffprobe_path() -> str:
    """Retourne le chemin vers ffprobe."""
    p = shutil.which("ffprobe")
    if p is None:
        for candidate in ["/usr/bin/ffprobe", "/usr/local/bin/ffprobe"]:
            if os.path.exists(candidate):
                return candidate
    return p or "ffprobe"


def _run_ffmpeg(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Exécute une commande FFmpeg."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg erreur (code {result.returncode}): {result.stderr}")
    return result


def _detect_audio_tracks(video_path: str) -> int:
    """Détecte le nombre de pistes audio dans un fichier vidéo."""
    try:
        import av

        with av.open(video_path) as container:
            audio_streams = [s for s in container.streams if s.type == "audio"]
            return max(len(audio_streams), 1)
    except Exception:
        pass
    
    result = subprocess.run(
        [
            _ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,index",
            "-of",
            "csv=p=0",
            video_path,
        ],
        capture_output=True,
        text=True,
    )
    
    audio_indices = [
        line
        for line in result.stdout.strip().splitlines()
        if line.startswith("audio")
    ]
    indices = set()
    for line in audio_indices:
        parts = line.split(",")
        if len(parts) >= 2:
            try:
                indices.add(int(parts[1]))
            except ValueError:
                pass
    return max(len(indices), 1)


def _upload_to_processing(local_path: str, key: str) -> None:
    """Upload un fichier vers le bucket de traitement S3."""
    settings = get_settings()
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
    )
    for bucket in [PROCESSING_BUCKET, settings.S3_BUCKET]:
        try:
            s3.create_bucket(Bucket=bucket)
        except Exception:
            pass
        try:
            s3.upload_file(local_path, bucket, key)
        except Exception:
            pass


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def extract_audio(
    self,
    video_path: str | None = None,
    media_path: str | None = None,
    output_dir: str = "/tmp/rythmoai_audio",
) -> dict[str, Any]:
    """
    Extraction des pistes audio (multi-pistes §11.2) → WAV 16 kHz mono (§13.1).

    Args:
        video_path: Chemin vers le fichier vidéo.
        media_path: Alias pour video_path.
        output_dir: Répertoire de sortie.

    Returns:
        dict: Informations sur les pistes extraites.
    """
    path = media_path or video_path
    if path is None:
        raise ValueError("video_path ou media_path est requis")
    
    os.makedirs(output_dir, exist_ok=True)
    basename = os.path.basename(path)
    name_root = os.path.splitext(basename)[0]

    # Détection nombre de pistes audio
    track_count = _detect_audio_tracks(path)

    extracted = []
    for i in range(track_count):
        output_path = os.path.join(output_dir, f"{name_root}_track_{i:02d}.wav")
        # Extraction + normalisation EBU R128 en une passe (loudnorm filter)
        # Filtre loudnorm : I=-23 LUFS (niveau cible EBU R128), TP=-2 dB (peak limit), LRA=11
        cmd = [
            _ffmpeg_path(),
            "-y",
            "-i",
            path,
            "-map",
            f"0:a:{i}" if track_count > 1 else "0:a:0",
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-af",
            "loudnorm=I=-23:TP=-2:LRA=11",
            output_path,
        ]
        _run_ffmpeg(cmd)
        # Upload vers bucket de traitement
        key = f"audio/{name_root}/track_{i:02d}.wav"
        _upload_to_processing(output_path, key)
        extracted.append(
            {
                "track_index": i,
                "local_path": output_path,
                "s3_key": key,
                "format": "wav_16k_mono",
            }
        )

    return {"video_path": path, "tracks": extracted, "track_count": track_count}
