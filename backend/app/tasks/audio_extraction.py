import os
import subprocess
import uuid
from celery import Celery
import boto3
from app.core.config import get_settings

celery_app = Celery("rythmoai", broker="redis://localhost:6379/0")

# Bucket de traitement (S3-compatible)
PROCESSING_BUCKET = "rythmoai-processing"

import shutil

def _ffmpeg_path():
    p = shutil.which("ffmpeg")
    if p is None:
        for candidate in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
            if os.path.exists(candidate):
                return candidate
    return p or "ffmpeg"

def _run_ffmpeg(cmd: list, timeout: int = 300):
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
    result = subprocess.run(
        ["/usr/bin/ffprobe", "-v", "error", "-show_entries", "stream=codec_type,index", "-of", "csv=p=0", video_path],
        capture_output=True, text=True
    )
    audio_indices = [line for line in result.stdout.strip().splitlines() if line.startswith("audio")]
    # Chaque ligne format: audio,0 etc. Compter unique index
    indices = set()
    for line in audio_indices:
        parts = line.split(",")
        if len(parts) >= 2:
            try:
                indices.add(int(parts[1]))
            except ValueError:
                pass
    return max(len(indices), 1)  # au moins 1 piste si fichier valide

def _upload_to_processing(local_path: str, key: str):
    settings = get_settings()
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
    )
    try:
        s3.create_bucket(Bucket=PROCESSING_BUCKET)
    except Exception:
        pass  # bucket peut déjà exister
    s3.upload_file(local_path, PROCESSING_BUCKET, key)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def extract_audio(self, video_path: str, output_dir: str = "/tmp/rythmoai_audio") -> dict:
    """Extraction des pistes audio (multi-pistes §11.2) → WAV 16 kHz mono (§13.1)."""
    os.makedirs(output_dir, exist_ok=True)
    basename = os.path.basename(video_path)
    name_root = os.path.splitext(basename)[0]

    # Détection nombre de pistes audio
    track_count = _detect_audio_tracks(video_path)

    extracted = []
    for i in range(track_count):
        output_path = os.path.join(output_dir, f"{name_root}_track_{i:02d}.wav")
        # Extraction + normalisation EBU R128 en une passe (loudnorm filter)
        # Filtre loudnorm : I=-23 LUFS (niveau cible EBU R128), TP=-2 dB (peak limit), LRA=11
        cmd = [
            _ffmpeg_path(),
            "-y",
            "-i", video_path,
            "-map", f"0:a:{i}" if track_count > 1 else "0:a:0",
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-af", "loudnorm=I=-23:TP=-2:LRA=11",
            output_path,
        ]
        _run_ffmpeg(cmd)
        # Upload vers bucket de traitement
        key = f"audio/{name_root}/track_{i:02d}.wav"
        _upload_to_processing(output_path, key)
        extracted.append({"track_index": i, "local_path": output_path, "s3_key": key, "format": "wav_16k_mono"})

    return {"video_path": video_path, "tracks": extracted, "track_count": track_count}
