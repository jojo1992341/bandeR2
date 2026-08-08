from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Replica, TranscriptSegment, Word

def compute_aggregate_score(replica_id: str, db: Session) -> float:
    """Score agrégé pondéré : transcription (50%), alignement (30%), diarisation (20%)."""
    # Simuler des valeurs issues du pipeline; en production, agréger segments et mots
    segment = db.query(TranscriptSegment).filter(TranscriptSegment.id == replica_id).first()
    words = db.query(Word).filter(Word.segment_id == replica_id).all()
    # Score transcription : moyenne des confidence_score des segments reliés
    # Pour simplification : utiliser un score de base depuis le segment parent
    trans_score = 0.85 if segment else 0.75
    # Score alignement : proportion de mots avec confidence > 0.8
    align_score = sum(1 for w in words if w.confidence_score and w.confidence_score > 0.8) / max(len(words), 1)
    # Score diarisation : cohérence des speaker_ids (moins de locuteurs = plus cohérent)
    speaker_ids = {w.speaker_id for w in words if w.speaker_id}
    diar_score = 0.9 if len(speaker_ids) <= 2 else 0.75
    score = (trans_score * 0.5) + (align_score * 0.3) + (diar_score * 0.2)
    return round(min(max(score, 0.0), 1.0), 3)
