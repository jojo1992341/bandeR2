from celery import shared_task
from celery.utils.log import get_task_logger
import subprocess
import os
import tempfile
from typing import Dict, Any

logger = get_task_logger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def extract_audio(self, media_asset_id: int, input_path: str, output_dir: str = "/tmp/rythmoai/audio") -> Dict[str, Any]:
    """
    Extract audio from video (WAV 16kHz mono, EBU R128 normalized).
    G-1.2
    """
    try:
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{media_asset_id}.wav")
        
        # Real ffmpeg command for production
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-ar", "16000",
            "-ac", "1",
            "-af", "loudnorm",
            "-vn",
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            logger.error(f"ffmpeg failed: {result.stderr}")
            raise Exception(f"Audio extraction failed: {result.stderr}")
        
        # Get duration
        duration_cmd = ["ffprobe", "-v", "error", "-show_entries", 
                       "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", output_path]
        duration_result = subprocess.run(duration_cmd, capture_output=True, text=True)
        duration_ms = int(float(duration_result.stdout.strip()) * 1000) if duration_result.returncode == 0 else 0
        
        return {
            "status": "success",
            "media_asset_id": media_asset_id,
            "audio_path": output_path,
            "duration_ms": duration_ms,
            "sample_rate": 16000
        }
        
    except Exception as exc:
        logger.error(f"extract_audio failed for {media_asset_id}: {exc}")
        self.retry(exc=exc)

@shared_task
def normalize_audio(media_asset_id: int, audio_path: str):
    """Normalize audio to EBU R128 (already done in extract)."""
    return {"status": "normalized", "media_asset_id": media_asset_id, "audio_path": audio_path}
