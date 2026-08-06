from celery import shared_task, group, chain
from celery.utils.log import get_task_logger
from typing import Dict, Any
from .audio import extract_audio, normalize_audio
from .transcription import transcribe, align_words, diarize

logger = get_task_logger(__name__)

@shared_task
def generate_rythmo_band(media_asset_id: int, transcript: dict) -> Dict[str, Any]:
    """Generate initial RythmoBand from transcript (G-1.8 placeholder)."""
    replicas = []
    for i, seg in enumerate(transcript.get("segments", [])):
        replicas.append({
            "order_index": i,
            "start_ms": seg["start_ms"],
            "end_ms": seg["end_ms"],
            "text": seg["text"],
            "speaker_id": 1
        })
    
    return {
        "status": "generated",
        "media_asset_id": media_asset_id,
        "replicas": replicas,
        "total_replicas": len(replicas)
    }

@shared_task(bind=True)
def run_full_pipeline(self, media_asset_id: int, input_video_path: str):
    """
    Full pipeline orchestration (G-1.6):
    extract_audio → normalize → transcribe → (align + diarize) → generate_rythmo
    """
    logger.info(f"Starting full pipeline for media {media_asset_id}")
    
    # Chain: extract → normalize → transcribe → parallel(align, diarize) → generate
    workflow = chain(
        extract_audio.s(media_asset_id, input_video_path),
        normalize_audio.s(),
        transcribe.s(media_asset_id=media_asset_id),
        group(
            align_words.s(media_asset_id=media_asset_id),
            diarize.s(media_asset_id=media_asset_id, audio_path="")
        ),
        generate_rythmo_band.s(media_asset_id=media_asset_id)
    )
    
    result = workflow.apply_async()
    return {
        "status": "pipeline_started",
        "media_asset_id": media_asset_id,
        "task_id": result.id
    }
