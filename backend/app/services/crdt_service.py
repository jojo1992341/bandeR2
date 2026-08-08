"""
CRDT Service §16.4 — Édition collaborative caractère par caractère
Remplace le verrouillage optimiste par réplique là où le volume d'usage le justifie (V2)

Implémente un RGA / Logoot-like CRDT pour le texte des répliques :
- Chaque caractère a un identifiant unique (site, counter) et une position (pos_id)
- Les opérations sont commutatives et convergentes (ordre d'application indifférent)
- Garantit convergence sans perte de données pour éditions concurrentes

Évaluation §16.4 : CRDT vs OT vs Verrouillage optimiste
- Verrouillage optimiste : simple, mais 409 Conflict en cas de concurrence (perte de temps)
- OT (Operational Transformation) : nécessite serveur central et transformation complexe
- CRDT : décentralisé, commutatif, idéal pour volume élevé et édition P2P, choisi pour V2
"""
import uuid
import time
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from app.models import Replica, ReplicaCrdtState, ReplicaCrdtOperation
from app.core.config import get_settings
from app.core.logging import logger

def _hash_site(site_id: str) -> int:
    """Hash déterministe pour tie-breaker"""
    return int(hashlib.sha256(site_id.encode()).hexdigest()[:8], 16) % 1000

class TextCRDT:
    """
    Implémentation Python du CRDT texte (compatible JS)
    - characters: liste triée de {char, id: {site, counter}, pos: [int], visible: bool}
    - version_vector: {site: max_counter}
    """
    def __init__(self, site_id: str = "default", initial_text: str = ""):
        self.site_id = site_id
        self.counter = 0
        self.characters: List[Dict[str, Any]] = []
        self.version_vector: Dict[str, int] = {site_id: 0}
        # Initialiser avec le texte initial
        for i, ch in enumerate(initial_text):
            self.characters.append({
                "char": ch,
                "id": {"site": "init", "counter": i},
                "pos": [i],
                "visible": True,
            })
        self.characters.sort(key=lambda c: (c["pos"], c["id"]["site"], c["id"]["counter"]))

    def _next_id(self) -> Dict[str, Any]:
        self.counter += 1
        self.version_vector[self.site_id] = self.counter
        return {"site": self.site_id, "counter": self.counter}

    def _generate_pos_between(self, left_pos: Optional[List[int]], right_pos: Optional[List[int]], site_id: str = None) -> List[int]:
        """Génère une position entre left et right (Logoot)"""
        site = site_id or self.site_id
        site_hash = _hash_site(site)
        # Cas simples
        if left_pos is None and right_pos is None:
            return [site_hash]
        if left_pos is None:
            # Avant le premier
            return [right_pos[0] - 1, site_hash]
        if right_pos is None:
            # Après le dernier
            return [left_pos[0] + 1, site_hash]
        # Entre deux positions : trouver la première différence
        # Si left = [1] et right = [2] -> [1, site_hash]
        # Si left = [1, 5] et right = [1, 6] -> [1, 5, site_hash]
        # Pour simplifier : si left[0] + 1 < right[0], on prend le milieu
        if left_pos[0] + 1 < right_pos[0]:
            return [(left_pos[0] + right_pos[0]) // 2, site_hash]
        else:
            # Besoin d'un niveau supplémentaire
            # Ex: [1] et [2] -> [1, site_hash] qui est > [1] et < [2] car [1, x] < [2]
            return left_pos + [site_hash]

    def _find_visible_index(self, logical_pos: int) -> int:
        """Convertit une position logique (index dans le texte visible) en index dans characters"""
        visible_count = 0
        for i, c in enumerate(self.characters):
            if c["visible"]:
                if visible_count == logical_pos:
                    return i
                visible_count += 1
        # Si logical_pos == len(visible), insérer à la fin
        return len(self.characters)

    def insert(self, logical_pos: int, char: str, site_id: str = None, counter: int = None, pos: List[int] = None) -> Dict[str, Any]:
        """Insère un caractère à la position logique"""
        site = site_id or self.site_id
        if counter is None:
            # Générer un nouvel ID
            if site == self.site_id:
                cid = self._next_id()
            else:
                # Pour les opérations distantes, on doit respecter le compteur fourni
                # Si non fourni, on incrémente
                self.counter += 1
                cid = {"site": site, "counter": self.counter}
                self.version_vector[site] = max(self.version_vector.get(site, 0), cid["counter"])
        else:
            cid = {"site": site, "counter": counter}
            self.version_vector[site] = max(self.version_vector.get(site, 0), counter)
            self.counter = max(self.counter, counter) if site == self.site_id else self.counter

        # Déterminer la position CRDT
        if pos is None:
            # Trouver les voisins visibles
            visible_chars = [c for c in self.characters if c["visible"]]
            left_pos = None
            right_pos = None
            if logical_pos > 0 and logical_pos <= len(visible_chars):
                left_char = visible_chars[logical_pos - 1]
                left_pos = left_char["pos"]
            if logical_pos < len(visible_chars):
                right_char = visible_chars[logical_pos]
                right_pos = right_char["pos"]
            pos = self._generate_pos_between(left_pos, right_pos, site)

        new_char = {
            "char": char,
            "id": cid,
            "pos": pos,
            "visible": True,
        }
        self.characters.append(new_char)
        self.characters.sort(key=lambda c: (c["pos"], c["id"]["site"], c["id"]["counter"]))
        return new_char

    def delete(self, logical_pos: int, site_id: str = None, counter: int = None) -> Optional[Dict[str, Any]]:
        """Supprime le caractère à la position logique (marque comme invisible)"""
        site = site_id or self.site_id
        visible_chars = [c for c in self.characters if c["visible"]]
        if logical_pos < 0 or logical_pos >= len(visible_chars):
            return None
        target = visible_chars[logical_pos]
        target["visible"] = False
        # Mettre à jour le version vector
        if site == self.site_id:
            self._next_id()
        else:
            if counter is not None:
                self.version_vector[site] = max(self.version_vector.get(site, 0), counter)
        return target

    def get_text(self) -> str:
        """Retourne le texte visible trié"""
        visible = [c for c in self.characters if c["visible"]]
        visible.sort(key=lambda c: (c["pos"], c["id"]["site"], c["id"]["counter"]))
        return "".join(c["char"] for c in visible)

    def getText(self) -> str:
        return self.get_text()

    def get_state(self) -> Dict[str, Any]:
        return {
            "characters": self.characters,
            "version_vector": self.version_vector,
            "text": self.get_text(),
        }

    def set_state(self, state: Dict[str, Any]):
        self.characters = state.get("characters", [])
        self.version_vector = state.get("version_vector", {})
        self.counter = max(self.version_vector.get(self.site_id, 0), 0)

    # Alias JS-friendly
    getState = get_state
    setState = set_state

    def merge(self, other: 'TextCRDT') -> None:
        """Fusionne un autre CRDT dans celui-ci (pour tester la convergence)"""
        # Fusionner les caractères : union, en gardant les plus récents pour les conflits de visibilité
        # Pour chaque caractère de l'autre, s'il n'existe pas chez nous, on l'ajoute
        existing_ids = {(c["id"]["site"], c["id"]["counter"]) for c in self.characters}
        for c in other.characters:
            cid = (c["id"]["site"], c["id"]["counter"])
            if cid not in existing_ids:
                self.characters.append(c)
                existing_ids.add(cid)
            else:
                # Si le caractère existe déjà, fusionner la visibilité (OR : si l'un est visible, on garde visible ?)
                # Pour les deletes, on veut que si l'un a supprimé, l'autre le voit comme supprimé
                # Donc on fait AND : visible seulement si tous les replicas le voient visible
                # Mais pour notre modèle, on considère que delete est définitif (visible=False l'emporte)
                for local in self.characters:
                    if (local["id"]["site"], local["id"]["counter"]) == cid:
                        # Si l'un est invisible, le résultat est invisible (delete l'emporte)
                        if not c["visible"]:
                            local["visible"] = False
                        break
        # Fusionner les version vectors (max)
        for site, counter in other.version_vector.items():
            self.version_vector[site] = max(self.version_vector.get(site, 0), counter)
        self.characters.sort(key=lambda c: (c["pos"], c["id"]["site"], c["id"]["counter"]))

class CrdtService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def is_enabled(self, studio_id: uuid.UUID = None, project_id: uuid.UUID = None) -> bool:
        """Vérifie si le CRDT est activé (feature flag + volume)"""
        # Feature flag global
        if self.settings.is_feature_enabled("crdt"):
            return True
        # Vérifier le volume : si le projet a beaucoup de répliques ou beaucoup d'éditeurs concurrents
        # Pour l'instant, on considère que le CRDT est activé si le studio a un plan pro/enterprise et que le projet a > 10 répliques
        # Ou si une variable d'env CRDT_VOLUME_THRESHOLD est dépassée
        import os
        volume_threshold = int(os.getenv("CRDT_VOLUME_THRESHOLD", "10"))
        if project_id:
            from app.models import Replica, MediaAsset
            # Compter les répliques du projet
            media_ids = [m.id for m in self.db.query(MediaAsset.id).filter(MediaAsset.project_id == project_id).all()]
            if media_ids:
                count = self.db.query(Replica).filter(Replica.media_id.in_(media_ids)).count()
                if count >= volume_threshold:
                    return True
        # Sinon, désactivé par défaut (garde le verrouillage optimiste)
        return False

    def get_or_create_state(self, replica_id: uuid.UUID, initial_text: str = "") -> ReplicaCrdtState:
        state = self.db.query(ReplicaCrdtState).filter(ReplicaCrdtState.replica_id == replica_id).first()
        if state:
            return state
        # Créer un nouvel état à partir du texte initial
        crdt = TextCRDT(site_id="init", initial_text=initial_text)
        import copy
        state = ReplicaCrdtState(
            replica_id=replica_id,
            characters=copy.deepcopy(crdt.characters),
            version_vector=dict(crdt.version_vector),
            clock=0,
            text=initial_text,
            enabled=True,
        )
        self.db.add(state)
        self.db.commit()
        self.db.refresh(state)
        return state

    def apply_operation(self, replica_id: uuid.UUID, site_id: str, op_type: str, position: int, char: Optional[str] = None, user_id: Optional[uuid.UUID] = None, pos: Optional[List[int]] = None) -> ReplicaCrdtState:
        """Applique une opération CRDT et persiste — pos optionnel pour convergence des éditions concurrentes"""
        # Charger l'état
        replica = self.db.query(Replica).filter(Replica.id == replica_id).first()
        if not replica:
            raise ValueError("Réplique non trouvée")
        state = self.get_or_create_state(replica_id, initial_text=replica.text or "")

        # Reconstruire le CRDT depuis l'état — copie profonde pour éviter la mutation partagée
        import copy
        crdt = TextCRDT(site_id=site_id)
        crdt.characters = copy.deepcopy(state.characters)
        crdt.version_vector = dict(state.version_vector)
        crdt.counter = state.clock

        # Appliquer l'opération
        timestamp = int(time.time() * 1000)
        if op_type == "insert":
            if not char or len(char) != 1:
                raise ValueError("Insert nécessite un caractère unique")
            new_char = crdt.insert(position, char, site_id=site_id, pos=pos)
            # Enregistrer l'opération
            op = ReplicaCrdtOperation(
                replica_id=replica_id,
                site_id=site_id,
                counter=new_char["id"]["counter"],
                op_type="insert",
                position=position,
                char=char,
                pos_id=new_char["pos"],
                version_vector=dict(crdt.version_vector),
                timestamp=timestamp,
                user_id=user_id,
            )
            self.db.add(op)
        elif op_type == "delete":
            deleted = crdt.delete(position, site_id=site_id)
            if not deleted:
                raise ValueError(f"Delete à la position {position} invalide")
            op = ReplicaCrdtOperation(
                replica_id=replica_id,
                site_id=site_id,
                counter=crdt.counter,
                op_type="delete",
                position=position,
                char=None,
                pos_id=deleted.get("pos"),
                version_vector=dict(crdt.version_vector),
                timestamp=timestamp,
                user_id=user_id,
            )
            self.db.add(op)
        else:
            raise ValueError(f"Type d'opération inconnu: {op_type}")

        # Mettre à jour l'état — forcer la détection de modification JSON en assignant une copie
        import copy
        from sqlalchemy.orm.attributes import flag_modified
        state.characters = copy.deepcopy(crdt.characters)
        flag_modified(state, "characters")
        state.version_vector = dict(crdt.version_vector)
        flag_modified(state, "version_vector")
        state.clock = crdt.counter
        state.text = crdt.get_text()
        state.updated_at = state.updated_at  # auto

        # Mettre à jour la réplique principale (texte matérialisé)
        replica.text = state.text
        replica.is_manually_edited = True
        # Incrémenter la version pour compatibilité avec l'ancien système (mais ne sera plus utilisée pour le verrouillage si CRDT activé)
        replica.version = (replica.version or 0) + 1

        self.db.commit()
        self.db.refresh(state)
        self.db.refresh(replica)
        return state

    def get_text(self, replica_id: uuid.UUID) -> str:
        state = self.db.query(ReplicaCrdtState).filter(ReplicaCrdtState.replica_id == replica_id).first()
        if state:
            return state.text
        # Fallback: retourner le texte de la réplique
        replica = self.db.query(Replica).filter(Replica.id == replica_id).first()
        return replica.text if replica else ""

    def get_state(self, replica_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        state = self.db.query(ReplicaCrdtState).filter(ReplicaCrdtState.replica_id == replica_id).first()
        if not state:
            return None
        return {
            "replica_id": str(state.replica_id),
            "characters": state.characters,
            "version_vector": state.version_vector,
            "clock": state.clock,
            "text": state.text,
            "enabled": state.enabled,
        }

    def merge_states(self, replica_id: uuid.UUID, remote_state: Dict[str, Any]) -> ReplicaCrdtState:
        """Fusionne un état distant (pour synchronisation)"""
        local_state = self.get_or_create_state(replica_id)
        # Reconstruire les deux CRDTs
        local_crdt = TextCRDT(site_id="local")
        local_crdt.characters = copy.deepcopy(local_state.characters)
        local_crdt.version_vector = dict(local_state.version_vector)

        remote_crdt = TextCRDT(site_id="remote")
        remote_crdt.characters = copy.deepcopy(remote_state.get("characters", []))
        remote_crdt.version_vector = dict(remote_state.get("version_vector", {}))

        # Merger
        local_crdt.merge(remote_crdt)

        # Persister — forcer la détection JSON
        import copy
        from sqlalchemy.orm.attributes import flag_modified
        local_state.characters = copy.deepcopy(local_crdt.characters)
        flag_modified(local_state, "characters")
        local_state.version_vector = dict(local_crdt.version_vector)
        flag_modified(local_state, "version_vector")
        local_state.text = local_crdt.get_text()
        # Mettre à jour la réplique
        replica = self.db.query(Replica).filter(Replica.id == replica_id).first()
        if replica:
            replica.text = local_state.text
            replica.version = (replica.version or 0) + 1

        self.db.commit()
        self.db.refresh(local_state)
        if replica:
            self.db.refresh(replica)
        return local_state

    def should_use_crdt(self, project_id: uuid.UUID) -> bool:
        """Détermine si on doit utiliser CRDT pour ce projet (volume élevé)"""
        return self.is_enabled(project_id=project_id)
