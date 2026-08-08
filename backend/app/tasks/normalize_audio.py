import shutil
from celery import Celery
import subprocess
import os

celery_app = Celery("rythmoai", broker="redis://localhost:6379/0")

def _ffmpeg_path():
    p = shutil.which("ffmpeg")
    if p is None:
        for candidate in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
            if os.path.exists(candidate):
                return candidate
    return p or "ffmpeg"

@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def normalize_audio(self, wav_path: str, output_path: str = None) -> dict:
    if output_path is None:
        output_path = wav_path.replace(".wav", "_normalized.wav")
    cmd = [
        _ffmpeg_path(),
        "-y",
        "-i", wav_path,
        "-af", "loudnorm=I=-23:TP=-2:LRA=11",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise self.retry(exc=RuntimeError(f"FFmpeg normalize failed: {result.stderr}"))
    return {"input": wav_path, "output": output_path, "status": "normalized_ebu_r128"}
