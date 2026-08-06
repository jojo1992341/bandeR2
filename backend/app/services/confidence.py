from typing import Dict, Any

def calculate_confidence_score(transcript: Dict[str, Any]) -> float:
    """
    Calculate aggregated confidence score per replica (G-1.7).
    Weighted average of transcription + alignment + diarization.
    """
    segments = transcript.get("segments", [])
    if not segments:
        return 0.0
    
    scores = []
    for seg in segments:
        trans_conf = seg.get("confidence", 0.85)
        align_conf = seg.get("alignment_confidence", 0.90)
        diar_conf = seg.get("diarization_confidence", 0.95)
        
        # Weighted: transcription 50%, alignment 30%, diarization 20%
        combined = (trans_conf * 0.5) + (align_conf * 0.3) + (diar_conf * 0.2)
        scores.append(combined)
    
    avg_score = sum(scores) / len(scores)
    return round(avg_score, 3)
