from typing import List, Dict, Any
import re

def generate_rythmo_band_from_transcript(
    transcript: Dict[str, Any],
    typographic_profile: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    Business rules engine for RythmoBand generation (G-1.8).
    
    - Segments into coherent replicas (speaker / silence / syntax)
    - Calculates available duration
    - Applies default typographic codes
    - No overlapping replicas
    """
    segments = transcript.get("segments", [])
    if not segments:
        return []
    
    replicas = []
    current_replica = None
    
    for i, seg in enumerate(segments):
        text = seg.get("text", "").strip()
        if not text:
            continue
            
        # Simple rule: new replica per segment for MVP
        # In production: better speaker change + silence detection + syntax boundaries
        
        replica = {
            "order_index": len(replicas),
            "start_ms": seg["start_ms"],
            "end_ms": seg["end_ms"],
            "text": apply_typographic_codes(text, typographic_profile),
            "speaker_id": seg.get("speaker_id", 1),
            "confidence_score": seg.get("confidence", 0.85),
            "codes": {}
        }
        
        # Prevent overlap (basic rule)
        if replicas and replica["start_ms"] < replicas[-1]["end_ms"]:
            replica["start_ms"] = replicas[-1]["end_ms"] + 50
        
        replicas.append(replica)
    
    return replicas

def apply_typographic_codes(text: str, profile: Dict = None) -> str:
    """Apply basic typographic codes (G-1.8 + G-2.4)."""
    result = text
    
    # Default rules (MVP)
    if profile and profile.get("use_brackets"):
        # Example: [pause] or [breath]
        pass
    
    # Capitalize first letter of sentence
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    
    # Add period if missing
    if result and not result.endswith(('.', '!', '?', '...')):
        result += "."
    
    return result
