"""
ReplicaLockManager §16.4 — Verrouillage optimiste par réplique avec notification WebSocket temps réel.

Gère les verrous d'édition par réplique :
  - Acquire/release/heartbeat avec TTL (expiration automatique)
  - Diffusion WebSocket en temps réel : « Camille édite cette réplique »
  - Un seul utilisateur peut verrouiller une réplique à la fois
  - Les verrous expirent après LOCK_TTL_SECONDS sans heartbeat
"""

import asyncio
import time
import uuid
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from fastapi import WebSocket
import json

# TTL du verrou en secondes (30s — le client doit envoyer un heartbeat toutes les ~10s)
LOCK_TTL_SECONDS: int = 30


@dataclass
class ReplicaLock:
    """Verrou d'édition sur une réplique."""
    replica_id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    project_id: uuid.UUID
    acquired_at: float = field(default_factory=time.monotonic)
    last_heartbeat: float = field(default_factory=time.monotonic)

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.last_heartbeat) > LOCK_TTL_SECONDS

    def heartbeat(self) -> None:
        self.last_heartbeat = time.monotonic()


@dataclass
class ProjectWSGroup:
    """Groupe de connexions WebSocket pour un projet."""
    project_id: uuid.UUID
    connections: List[WebSocket] = field(default_factory=list)

    async def broadcast(self, message: dict) -> None:
        """Diffuse un message JSON à toutes les connexions actives du projet."""
        payload = json.dumps(message)
        stale: List[WebSocket] = []
        for ws in self.connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.connections.remove(ws)


class ReplicaLockManager:
    """
    Singleton gérant les verrous de réplique et les connexions WebSocket.

    Thread-safety : conçu pour usage async (FastAPI event loop).
    Les verrous sont en mémoire (pas de Redis) — suffisant pour une instance MVP.
    Pour multi-instance, migrer vers Redis + Redis Pub/Sub.
    """

    def __init__(self) -> None:
        # replica_id → ReplicaLock
        self._locks: Dict[uuid.UUID, ReplicaLock] = {}
        # project_id → ProjectWSGroup
        self._ws_groups: Dict[uuid.UUID, ProjectWSGroup] = {}

    # ── Verrous ──────────────────────────────────────────────

    def acquire_lock(
        self,
        replica_id: uuid.UUID,
        user_id: uuid.UUID,
        user_name: str,
        project_id: uuid.UUID,
    ) -> Tuple[bool, Optional[ReplicaLock]]:
        """
        Tente d'acquérir un verrou sur une réplique.

        Returns:
            (success, current_lock)
            - (True, lock)   si le verrou a été acquis
            - (False, lock)  si un autre utilisateur tient le verrou (lock = holder)
            - (False, None)  ne devrait pas arriver
        """
        existing = self._locks.get(replica_id)

        # Si un verrou existe et n'est pas expiré
        if existing and not existing.is_expired:
            if existing.user_id == user_id:
                # Même utilisateur : heartbeat implicite
                existing.heartbeat()
                return (True, existing)
            # Autre utilisateur : verrou refusé
            return (False, existing)

        # Verrou expiré ou inexistant → acquérir
        lock = ReplicaLock(
            replica_id=replica_id,
            user_id=user_id,
            user_name=user_name,
            project_id=project_id,
        )
        self._locks[replica_id] = lock
        return (True, lock)

    def release_lock(self, replica_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """
        Relâche un verrou si l'utilisateur est le propriétaire.
        Returns True si le verrou a été relâché.
        """
        existing = self._locks.get(replica_id)
        if existing and existing.user_id == user_id:
            del self._locks[replica_id]
            return True
        return False

    def heartbeat(self, replica_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """
        Renouvelle le TTL du verrou.
        Returns True si le verrou existe et appartient à l'utilisateur.
        """
        existing = self._locks.get(replica_id)
        if existing and existing.user_id == user_id:
            existing.heartbeat()
            return True
        return False

    def get_lock(self, replica_id: uuid.UUID) -> Optional[ReplicaLock]:
        """Retourne le verrou actif (non expiré) ou None."""
        lock = self._locks.get(replica_id)
        if lock and not lock.is_expired:
            return lock
        # Nettoyage si expiré
        if lock and lock.is_expired:
            del self._locks[replica_id]
        return None

    def get_locks_for_project(self, project_id: uuid.UUID) -> Dict[uuid.UUID, ReplicaLock]:
        """Retourne tous les verrous actifs pour un projet."""
        self._cleanup_expired()
        return {
            rid: lock
            for rid, lock in self._locks.items()
            if lock.project_id == project_id and not lock.is_expired
        }

    def _cleanup_expired(self) -> None:
        """Supprime les verrous expirés."""
        expired = [rid for rid, lock in self._locks.items() if lock.is_expired]
        for rid in expired:
            del self._locks[rid]

    # ── WebSocket ────────────────────────────────────────────

    def add_ws(self, project_id: uuid.UUID, websocket: WebSocket) -> None:
        group = self._ws_groups.setdefault(project_id, ProjectWSGroup(project_id=project_id))
        group.connections.append(websocket)

    def remove_ws(self, project_id: uuid.UUID, websocket: WebSocket) -> None:
        group = self._ws_groups.get(project_id)
        if group:
            if websocket in group.connections:
                group.connections.remove(websocket)
            if not group.connections:
                del self._ws_groups[project_id]

    async def broadcast_lock_acquired(
        self,
        project_id: uuid.UUID,
        replica_id: uuid.UUID,
        user_id: uuid.UUID,
        user_name: str,
    ) -> None:
        """Diffuse « user_name édite cette réplique » à tous les clients du projet."""
        group = self._ws_groups.get(project_id)
        if group:
            await group.broadcast({
                "type": "replica:lock_acquired",
                "replica_id": str(replica_id),
                "user_id": str(user_id),
                "user_name": user_name,
            })

    async def broadcast_lock_released(
        self,
        project_id: uuid.UUID,
        replica_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Diffuse la libération du verrou."""
        group = self._ws_groups.get(project_id)
        if group:
            await group.broadcast({
                "type": "replica:lock_released",
                "replica_id": str(replica_id),
                "user_id": str(user_id),
            })

    async def broadcast_replica_updated(
        self,
        project_id: uuid.UUID,
        replica_id: uuid.UUID,
        user_id: uuid.UUID,
        user_name: str,
        version: int,
        changes: dict,
    ) -> None:
        """Diffuse une mise à jour de réplique (après commit optimiste)."""
        group = self._ws_groups.get(project_id)
        if group:
            await group.broadcast({
                "type": "replica:updated",
                "replica_id": str(replica_id),
                "user_id": str(user_id),
                "user_name": user_name,
                "version": version,
                "changes": changes,
            })


# Singleton global
lock_manager = ReplicaLockManager()
