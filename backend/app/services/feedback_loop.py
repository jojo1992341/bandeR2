from typing import Dict, Any
import hashlib

def log_correction(
    replica_id: int,
    correction_type: str,
    original_value: str,
    corrected_value: str,
    studio_id: int,
    consent_given: bool = False
) -> Dict[str, Any]:
    """
    G-3.6 — Anonymous feedback loop for model improvement.
    Only logs if studio has given explicit consent.
    """
    if not consent_given:
        return {"logged": False, "reason": "No consent"}
    
    # Anonymize
    hash_id = hashlib.sha256(f"{studio_id}:{replica_id}".encode()).hexdigest()[:12]
    
    return {
        "logged": True,
        "anonymized_id": hash_id,
        "correction_type": correction_type,
        "delta": len(corrected_value) - len(original_value),
        "timestamp": "2026-08-06T14:xx:xx"
    }
