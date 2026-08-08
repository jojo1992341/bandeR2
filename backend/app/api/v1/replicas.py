from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import Optional, List
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

class ReplicaSplitIn(BaseModel):
    split_ms: Optional[int] = None

class ReplicaMergeIn(BaseModel):
    replica_ids: List[uuid.UUID]

def _serialize_replica(r: Replica) -> dict:
    return {
        "id": str(r.id),
        "media_id": str(r.media_id),
        "speaker_id": str(r.speaker_id) if r.speaker_id else None,
        "text": r.text,
        "start_ms": r.start_ms,
        "end_ms": r.end_ms,
        "order_index": r.order_index,
        "typo_codes": r.typo_codes,
        "confidence_score": float(r.confidence_score) if r.confidence_score is not None else None,
        "is_manually_edited": r.is_manually_edited,
        "breath_marker": r.breath_marker,
    }

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

@router.post("/replicas/{replica_id}/split", response_model=dict)
def split_replica(
    replica_id: uuid.UUID,
    data: ReplicaSplitIn,
    db: Session = Depends(get_db),
):
    """
    Scinde une réplique en deux au point split_ms.
    §10.2 POST /replicas/{id}/split
    - Si split_ms non fourni, coupe au milieu temporel.
    - Produit deux Replica cohérentes en timing : [start, split_ms) et [split_ms, end)
    - Répartit le texte proportionnellement au ratio temporel (découpage au mot près)
    """
    replica = db.query(Replica).filter(Replica.id == replica_id).first()
    if not replica:
        raise HTTPException(status_code=404, detail="Réplique non trouvée")

    split_ms = data.split_ms
    if split_ms is None:
        split_ms = (replica.start_ms + replica.end_ms) // 2

    # Validation : split doit être strictement à l'intérieur
    if split_ms <= replica.start_ms or split_ms >= replica.end_ms:
        raise HTTPException(status_code=422, detail="split_ms doit être strictement entre start_ms et end_ms")

    original_end = replica.end_ms
    original_start = replica.start_ms
    original_text = replica.text or ""
    original_order = replica.order_index

    # Historisation avant modification
    db.add(ReplicaHistory(
        replica_id=replica.id,
        previous_text=replica.text,
        previous_start_ms=replica.start_ms,
        previous_end_ms=replica.end_ms,
        previous_speaker_id=replica.speaker_id,
        updated_by="system",
    ))

    # Découpage du texte proportionnellement au ratio temporel
    words = original_text.split()
    if len(words) <= 1:
        # Pas de mots distincts : coupe caractères au milieu
        mid = max(1, len(original_text) // 2)
        # Trouver un espace proche pour éviter couper un mot en plein milieu si possible
        # Si la coupe tombe au milieu d'un mot, on tente de couper au plus proche espace
        # Fallback : coupe brute
        if " " in original_text:
            # Déjà géré par split words >1, donc ici pas d'espace, coupe brute
            text1 = original_text[:mid].strip()
            text2 = original_text[mid:].strip()
            if not text1:
                text1 = original_text
            if not text2:
                text2 = original_text
        else:
            text1 = original_text[:mid].strip() if len(original_text) > 2 else original_text
            text2 = original_text[mid:].strip() if len(original_text) > 2 else original_text
            if not text1:
                text1 = original_text[:1]
            if not text2:
                text2 = original_text[1:] if len(original_text) > 1 else original_text
    else:
        duration = original_end - original_start
        ratio = (split_ms - original_start) / duration if duration > 0 else 0.5
        ratio = max(0.05, min(0.95, ratio))
        # Répartition par nombre de mots
        split_idx = max(1, min(len(words) - 1, round(len(words) * ratio)))
        # Sécurité : éviter split_idx hors bornes
        text1 = " ".join(words[:split_idx]).strip()
        text2 = " ".join(words[split_idx:]).strip()
        if not text1:
            text1 = words[0]
        if not text2:
            text2 = words[-1]

    # Décaler les order_index des répliques suivantes pour insérer la nouvelle
    siblings_after = db.query(Replica).filter(
        Replica.media_id == replica.media_id,
        Replica.order_index > original_order,
    ).order_by(Replica.order_index).all()
    for s in siblings_after:
        s.order_index += 1

    # Mettre à jour la réplique originale (première moitié)
    replica.text = text1
    replica.end_ms = split_ms
    replica.is_manually_edited = True

    # Créer la seconde moitié
    new_replica = Replica(
        id=uuid.uuid4(),
        media_id=replica.media_id,
        speaker_id=replica.speaker_id,
        text=text2,
        start_ms=split_ms,
        end_ms=original_end,
        order_index=original_order + 1,
        typo_codes=replica.typo_codes if replica.typo_codes is not None else {},
        confidence_score=replica.confidence_score,
        is_manually_edited=True,
        breath_marker=replica.breath_marker,
    )
    db.add(new_replica)
    db.commit()
    db.refresh(replica)
    db.refresh(new_replica)

    return {
        "replicas": [_serialize_replica(replica), _serialize_replica(new_replica)],
        "split_ms": split_ms,
        "status": "split",
    }

@router.post("/replicas/merge", response_model=dict)
def merge_replicas(
    data: ReplicaMergeIn,
    db: Session = Depends(get_db),
):
    """
    Fusionne plusieurs répliques en une seule.
    §10.2 POST /replicas/merge
    - replica_ids : liste d'au moins 2 UUIDs
    - Toutes doivent appartenir au même media_id
    - Produit une seule Replica cohérente en timing : [min(start), max(end))
    """
    if not data.replica_ids or len(data.replica_ids) < 2:
        raise HTTPException(status_code=422, detail="replica_ids doit contenir au moins 2 identifiants")

    # Récupérer toutes les répliques demandées
    replicas = db.query(Replica).filter(Replica.id.in_(data.replica_ids)).all()
    if len(replicas) != len(data.replica_ids):
        raise HTTPException(status_code=404, detail="Une ou plusieurs répliques non trouvées")

    # Vérifier cohérence media_id
    media_ids = {r.media_id for r in replicas}
    if len(media_ids) > 1:
        raise HTTPException(status_code=422, detail="Toutes les répliques doivent appartenir au même média")

    # Trier par start_ms puis order_index pour garantir l'ordre
    replicas_sorted = sorted(replicas, key=lambda r: (r.start_ms, r.order_index))

    # Optionnel : vérifier qu'elles sont triées et éventuellement contiguës, mais on autorise tout même avec gaps
    # On fusionnera en prenant le plus petit start et plus grand end, texte concaténé

    merged_text = " ".join([r.text.strip() for r in replicas_sorted if r.text and r.text.strip()])
    if not merged_text:
        merged_text = replicas_sorted[0].text

    merged_start = min(r.start_ms for r in replicas_sorted)
    merged_end = max(r.end_ms for r in replicas_sorted)
    if merged_start >= merged_end:
        raise HTTPException(status_code=422, detail="Fusion invalide : start_ms doit être < end_ms")

    # Le premier dans l'ordre trié sera conservé et mis à jour
    primary = replicas_sorted[0]
    others = replicas_sorted[1:]

    # Historisation du primary avant fusion
    db.add(ReplicaHistory(
        replica_id=primary.id,
        previous_text=primary.text,
        previous_start_ms=primary.start_ms,
        previous_end_ms=primary.end_ms,
        previous_speaker_id=primary.speaker_id,
        updated_by="system",
    ))
    # Historiser aussi les autres répliques supprimées (optionnel pour audit)
    for r in others:
        db.add(ReplicaHistory(
            replica_id=r.id,
            previous_text=r.text,
            previous_start_ms=r.start_ms,
            previous_end_ms=r.end_ms,
            previous_speaker_id=r.speaker_id,
            updated_by="system-merge-deleted",
        ))

    min_order = min(r.order_index for r in replicas_sorted)
    max_order = max(r.order_index for r in replicas_sorted)
    # Calculer score de confiance moyen si disponible
    scores = [float(r.confidence_score) for r in replicas_sorted if r.confidence_score is not None]
    avg_score = sum(scores) / len(scores) if scores else primary.confidence_score

    # Merger les typo_codes (union simple)
    merged_typo = {}
    for r in replicas_sorted:
        if r.typo_codes:
            merged_typo.update(r.typo_codes)

    # Mettre à jour primary
    primary.text = merged_text
    primary.start_ms = merged_start
    primary.end_ms = merged_end
    primary.confidence_score = avg_score
    primary.is_manually_edited = True
    primary.typo_codes = merged_typo
    primary.order_index = min_order
    # Conserver breath_marker si au moins une réplique le porte
    primary.breath_marker = any(r.breath_marker for r in replicas_sorted)

    # Supprimer les autres répliques
    for r in others:
        db.delete(r)

    # Réordonner les répliques suivantes pour combler le gap d'order_index
    # Le gap est len(others) car on a supprimé N-1 répliques
    shift = len(others)
    # Il faut décaler celles dont order_index > max_order
    media_id = primary.media_id
    siblings_after = db.query(Replica).filter(
        Replica.media_id == media_id,
        Replica.order_index > max_order,
    ).order_by(Replica.order_index).all()
    for s in siblings_after:
        s.order_index -= shift

    db.commit()
    db.refresh(primary)

    return {
        "replica": _serialize_replica(primary),
        "merged_count": len(replicas_sorted),
        "status": "merged",
    }
