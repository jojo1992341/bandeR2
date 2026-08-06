from typing import Dict, Any, List
import re

def calculate_speech_rate(replica: Dict[str, Any], language: str = "fr") -> Dict[str, Any]:
    """
    G-2.2 — Speech rate (syllables/second) calculation.
    French target: 5–7 syll/s
    """
    text = replica.get("text", "")
    
    # Simple French syllable estimation
    # More accurate version would use phonetic analysis
    words = re.findall(r'\b\w+\b', text.lower())
    
    # French syllable estimation (rough)
    syllable_count = 0
    for word in words:
        # Count vowel groups
        vowels = len(re.findall(r'[aeiouyàâäéèêëîïôöùûü]', word))
        syllable_count += max(1, vowels)
    
    duration_sec = (replica.get("end_ms", 0) - replica.get("start_ms", 0)) / 1000
    if duration_sec <= 0:
        return {"syll_per_sec": 0, "status": "warning"}
    
    rate = syllable_count / duration_sec
    
    # Thresholds (French)
    status = "normal"
    if rate > 7.5:
        status = "too_fast"
    elif rate < 4.5:
        status = "too_slow"
    
    return {
        "syll_per_sec": round(rate, 2),
        "syllable_count": syllable_count,
        "duration_sec": round(duration_sec, 2),
        "status": status,
        "language": language
    }
