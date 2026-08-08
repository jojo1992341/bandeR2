"""
WebSocket & REST endpoints pour le verrouillage optimiste par réplique §16.4.

WebSocket :  ws://…/ws/projects/{project_id}/replicas
  - Connexion temps réel pour recevoir les événements de verrouillage
  - Messages entrants : heartbeat, acquire_lock, release_lock
  - Messages sortants : replica:lock_acquired, replica:lock_released, replica:updated

REST :
  - POST   /api/v1/replicas/{id}/lock      — acquérir un verrou
  - DELETE /api/v1/replicas/{id}/lock      — relâcher un verrou
  - POST   /api/v1/replicas/{id}/heartbeat — renouveler le TTL
"""

import uuid
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import Replica
from app.services.replica_lock_manager import lock_manager

router = APIRouter()


# ── Modèles Pydantic ──────────────────────────────────────────

class LockAcquireIn(BaseModel):
    user_id: uuid.UUID
    user_name: str

class LockAcquireOut(BaseModel):
    acquired: bool
    locked_by: dict | None = None  # {user_id, user_name} si verrouillé par un autre
    message: str | None = None

class HeartbeatIn(BaseModel):
    user_id: uuid.UUID

class HeartbeatOut(BaseModel):
    ok: bool


# ── Helper : extraire project_id d'une réplique ───────────────

def _get_replica_project_id(replica_id: uuid.UUID, db: Session) -> uuid.UUID | None:
    """Récupère le project_id via media_id → Project."""
    replica = db.query(Replica).filter(Replica.id == replica_id).first()
    if not replica:
        return None
    # On a besoin du projet pour broadcaster — on le déduit via media
    from app.models import MediaAsset, Project
    media = db.query(MediaAsset).filter(MediaAsset.id == replica.media_id).first()
    if not media:
        return None
    return media.project_id


# ── REST : Acquérir un verrou ────────────────────────────────

@router.post("/replicas/{replica_id}/lock", response_model=LockAcquireOut)
async def acquire_replica_lock(
    replica_id: uuid.UUID,
    data: LockAcquireIn,
    db: Session = Depends(get_db),
):
    """§16.4 — Tente d'acquérir un verrou d'édition sur une réplique."""
    replica = db.query(Replica).filter(Replica.id == replica_id).first()
    if not replica:
        raise HTTPException(status_code=404, detail="Réplique non trouvée")

    project_id = _get_replica_project_id(replica_id, db)
    if not project_id:
        raise HTTPException(status_code=404, detail="Projet non trouvé pour cette réplique")

    success, current = lock_manager.acquire_lock(
        replica_id=replica_id,
        user_id=data.user_id,
        user_name=data.user_name,
        project_id=project_id,
    )

    if success:
        # Notifier les autres utilisateurs via WebSocket
        await lock_manager.broadcast_lock_acquired(
            project_id=project_id,
            replica_id=replica_id,
            user_id=data.user_id,
            user_name=data.user_name,
        )
        return LockAcquireOut(
            acquired=True,
            message=f"Verrou acquis sur la réplique {replica_id}",
        )
    else:
        return LockAcquireOut(
            acquired=False,
            locked_by={
                "user_id": str(current.user_id),
                "user_name": current.user_name,
            },
            message=f"Réplique verrouillée par {current.user_name}",
        )


# ── REST : Relâcher un verrou ────────────────────────────────

@router.delete("/replicas/{replica_id}/lock", response_model=dict)
async def release_replica_lock(
    replica_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """§16.4 — Relâche un verrou d'édition (user_id en query param)."""
    project_id = _get_replica_project_id(replica_id, db)

    released = lock_manager.release_lock(replica_id=replica_id, user_id=user_id)

    if released and project_id:
        await lock_manager.broadcast_lock_released(
            project_id=project_id,
            replica_id=replica_id,
            user_id=user_id,
        )

    return {"released": released}


# ── REST : Heartbeat ─────────────────────────────────────────

@router.post("/replicas/{replica_id}/heartbeat", response_model=HeartbeatOut)
async def replica_lock_heartbeat(
    replica_id: uuid.UUID,
    data: HeartbeatIn,
):
    """§16.4 — Renouvelle le TTL du verrou (le client doit envoyer toutes les ~10s)."""
    ok = lock_manager.heartbeat(replica_id=replica_id, user_id=data.user_id)
    return HeartbeatOut(ok=ok)


# ── REST : Statut du verrou ──────────────────────────────────

@router.get("/replicas/{replica_id}/lock", response_model=dict)
async def get_replica_lock_status(replica_id: uuid.UUID):
    """§16.4 — Retourne le statut du verrou sur une réplique."""
    lock = lock_manager.get_lock(replica_id)
    if lock:
        return {
            "locked": True,
            "user_id": str(lock.user_id),
            "user_name": lock.user_name,
            "acquired_at": lock.acquired_at,
        }
    return {"locked": False}


# ── WebSocket : Événements temps réel ────────────────────────

@router.websocket("/ws/projects/{project_id}/replicas")
async def ws_replica_events(websocket: WebSocket, project_id: uuid.UUID):
    """
    §16.4 — WebSocket pour les événements de verrouillage de répliques.

    Messages sortants (serveur → client) :
      - { type: "replica:lock_acquired", replica_id, user_id, user_name }
      - { type: "replica:lock_released", replica_id, user_id }
      - { type: "replica:updated", replica_id, user_id, user_name, version, changes }
      - { type: "lock_snapshot", locks: { replica_id: { user_id, user_name } } }

    Messages entrants (client → serveur) :
      - { type: "heartbeat", replica_id, user_id }  — renouveler un verrou
      - { type: "acquire_lock", replica_id, user_id, user_name }  — acquérir un verrou
      - { type: "release_lock", replica_id, user_id }  — relâcher un verrou
    """
    await websocket.accept()
    lock_manager.add_ws(project_id, websocket)

    # Envoyer l'état initial des verrous du projet
    locks = lock_manager.get_locks_for_project(project_id)
    snapshot = {
        "type": "lock_snapshot",
        "locks": {
            str(rid): {
                "user_id": str(lock.user_id),
                "user_name": lock.user_name,
            }
            for rid, lock in locks.items()
        },
    }
    await websocket.send_json(snapshot)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "heartbeat":
                rid_str = msg.get("replica_id")
                uid_str = msg.get("user_id")
                if rid_str and uid_str:
                    try:
                        rid = uuid.UUID(rid_str)
                        uid = uuid.UUID(uid_str)
                        ok = lock_manager.heartbeat(rid, uid)
                        await websocket.send_json({
                            "type": "heartbeat_ack",
                            "replica_id": rid_str,
                            "ok": ok,
                        })
                    except (ValueError, AttributeError):
                        pass

            elif msg_type == "acquire_lock":
                rid_str = msg.get("replica_id")
                uid_str = msg.get("user_id")
                uname = msg.get("user_name", "Inconnu")
                if rid_str and uid_str:
                    try:
                        rid = uuid.UUID(rid_str)
                        uid = uuid.UUID(uid_str)
                        success, current = lock_manager.acquire_lock(rid, uid, uname, project_id)
                        if success:
                            await lock_manager.broadcast_lock_acquired(project_id, rid, uid, uname)
                        await websocket.send_json({
                            "type": "acquire_lock_result",
                            "replica_id": rid_str,
                            "acquired": success,
                            "locked_by": {
                                "user_id": str(current.user_id),
                                "user_name": current.user_name,
                            } if not success and current else None,
                        })
                    except (ValueError, AttributeError):
                        pass

            elif msg_type == "release_lock":
                rid_str = msg.get("replica_id")
                uid_str = msg.get("user_id")
                if rid_str and uid_str:
                    try:
                        rid = uuid.UUID(rid_str)
                        uid = uuid.UUID(uid_str)
                        released = lock_manager.release_lock(rid, uid)
                        if released:
                            await lock_manager.broadcast_lock_released(project_id, rid, uid)
                        await websocket.send_json({
                            "type": "release_lock_result",
                            "replica_id": rid_str,
                            "released": released,
                        })
                    except (ValueError, AttributeError):
                        pass

    except WebSocketDisconnect:
        pass
    finally:
        lock_manager.remove_ws(project_id, websocket)
