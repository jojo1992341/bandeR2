from celery import shared_task
from typing import List, Dict

@shared_task(bind=True, max_retries=2)
def transcribe(self, media_asset_id: int, audio_path: str, language: str = "fr"):
    """Whisper Large v3 transcription task."""
    # Placeholder implementation
    return {
        "media_asset_id": media_asset_id,
        "language": language,
        "segments": [
            {"start_ms": 0, "end_ms": 4500, "text": "Bonjour, comment allez-vous ?", "confidence": 0.95}
        ],
        "words": [],
        "speakers": [{"id": 1, "name": "Speaker 1"}],
        "wer_estimate": 0.12
    }

@shared_task
def align_words(media_asset_id: int, transcript: dict):
    """WhisperX forced alignment."""
    return {"status": "aligned", "media_asset_id": media_asset_id}

@shared_task
def diarize(media_asset_id: int, audio_path: str):
    """pyannote speaker diarization."""
    return {"status": "diarized", "speakers": 2}
