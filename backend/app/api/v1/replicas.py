from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import Optional
import uuid
from app.core.database import get_db
from app.models import Replica, ReplicaHistory, MediaAsset

router = APIRouter()

class ReplicaPatchIn(BaseModel):
    text: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    speaker_id: Optional[uuid.UUID] = None
    typo_codes: Optional[dict] = None
    overlap_allowed: bool = False

@router.patch("/replicas/{replica_id}", response_model=dict)
def patch_replica(
    replica_id: uuid.UUID,
    data: ReplicaPatchIn,
    db: Session = Depends(get_db),
):
    # Anti-IDOR / existence
    replica = db.query(Replica).filter(Replica.id == replica_id).first()
    if not replica:
        raise HTTPException(status_code=404, detail="Réplique non trouvée")
    # Validation start < end
    new_start = data.start_ms if data.start_ms is not None else replica.start_ms
    new_end = data.end_ms if data.end_ms is not None else replica.end_ms
    if new_start >= new_end:
        raise HTTPException(status_code=422, detail="start_ms doit être < end_ms")
    # Vérifier chevauchement sauf si autorisé
    if not data.overlap_allowed:
        siblings = db.query(Replica).filter(
            Replica.media_id == replica.media_id,
            Replica.id != replica.id,
        ).all()
        for s in siblings:
            if not (new_end <= s.start_ms or new_start >= s.end_ms):
                raise HTTPException(status_code=422, detail=f"Chevauchement interdit avec réplique {s.id}")
    # Créer historique avant modification
    db.add(ReplicaHistory(
        replica_id=replica.id,
        previous_text=replica.text,
        previous_start_ms=replica.start_ms,
        previous_end_ms=replica.end_ms,
        previous_speaker_id=replica.speaker_id,
        updated_by="system",
    ))
    # Appliquer modifications
    if data.text is not None:
        replica.text = data.text
    if data.start_ms is not None:
        replica.start_ms = data.start_ms
    if data.end_ms is not None:
        replica.end_ms = data.end_ms
    if data.speaker_id is not None:
        replica.speaker_id = data.speaker_id
    if data.typo_codes is not None:
        replica.typo_codes = data.typo_codes
    replica.is_manually_edited = True
    db.commit()
    return {"id": str(replica.id), "status": "updated", "is_manually_edited": True}
