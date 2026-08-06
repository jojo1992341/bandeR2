from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Dict, List
from app.core.security import require_role
import json
from datetime import datetime

router = APIRouter(prefix="/collaboration", tags=["collaboration"])

class CommentCreate(BaseModel):
    replica_id: int
    text: str

class CommentResponse(BaseModel):
    id: int
    replica_id: int
    text: str
    author: str
    created_at: str

# In-memory stores for MVP
active_locks = {}          # replica_id -> user
comments_db = {}
connected_users = {}       # project_id -> list of websockets

@router.post("/replicas/{replica_id}/lock")
async def lock_replica(replica_id: int, current_user=Depends(require_role("adaptateur"))):
    """G-2.7 — Optimistic locking with notification."""
    if replica_id in active_locks:
        return {"locked": True, "by": active_locks[replica_id], "can_edit": False}
    
    active_locks[replica_id] = current_user.sub
    return {"locked": True, "by": current_user.sub, "can_edit": True}

@router.delete("/replicas/{replica_id}/lock")
async def unlock_replica(replica_id: int, current_user=Depends(require_role("adaptateur"))):
    if replica_id in active_locks and active_locks[replica_id] == current_user.sub:
        del active_locks[replica_id]
    return {"unlocked": True}

@router.post("/replicas/{replica_id}/comments", response_model=CommentResponse)
async def add_comment(replica_id: int, comment: CommentCreate, current_user=Depends(require_role("adaptateur"))):
    """G-2.8 — Collaborative comments."""
    cid = len(comments_db) + 1
    comments_db[cid] = {
        "id": cid,
        "replica_id": replica_id,
        "text": comment.text,
        "author": current_user.sub,
        "created_at": datetime.now().isoformat()
    }
    return comments_db[cid]

@router.get("/replicas/{replica_id}/comments")
async def get_comments(replica_id: int, current_user=Depends(require_role("guest"))):
    return [c for c in comments_db.values() if c["replica_id"] == replica_id]

@router.websocket("/ws/{project_id}")
async def collaboration_ws(websocket: WebSocket, project_id: int):
    """G-2.7 — Real-time collaboration WebSocket."""
    await websocket.accept()
    if project_id not in connected_users:
        connected_users[project_id] = []
    connected_users[project_id].append(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            # Broadcast to all users in project
            for ws in connected_users[project_id]:
                if ws != websocket:
                    await ws.send_text(json.dumps({
                        "type": message.get("type", "update"),
                        "from": message.get("from"),
                        "data": message.get("data")
                    }))
    except WebSocketDisconnect:
        connected_users[project_id].remove(websocket)
