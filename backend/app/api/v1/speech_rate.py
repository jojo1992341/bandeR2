from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.services.speech_rate_service import (
    count_syllables,
    compute_speech_rate,
    evaluate_speech_rate,
    DEFAULT_SPEECH_RATE_THRESHOLDS,
)

router = APIRouter()


class SpeechRateEvalIn(BaseModel):
    text: str
    duration_ms: int
    language: str = "fr"
    custom_thresholds: Optional[Dict[str, Any]] = None


@router.post("/speech-rate/evaluate", response_model=Dict[str, Any])
@router.post("/api/v1/speech-rate/evaluate", response_model=Dict[str, Any])
def evaluate_speech_rate_endpoint(data: SpeechRateEvalIn):
    if data.duration_ms < 0:
        raise HTTPException(
            status_code=422, detail="duration_ms doit être positif"
        )

    res = evaluate_speech_rate(
        text=data.text,
        duration_ms=data.duration_ms,
        language=data.language,
        custom_thresholds=data.custom_thresholds,
    )
    return res


@router.get("/speech-rate/thresholds", response_model=Dict[str, Any])
@router.get("/api/v1/speech-rate/thresholds", response_model=Dict[str, Any])
def get_speech_rate_thresholds():
    return {
        "status": "ok",
        "thresholds_by_language": DEFAULT_SPEECH_RATE_THRESHOLDS,
        "reference": "5-7 syll/s en FR standard (§12.3)",
    }
