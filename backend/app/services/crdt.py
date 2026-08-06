from typing import Dict, Any, List

class CRDTReplica:
    """Simple CRDT-like structure for character-level collaborative editing (G-4.3)."""
    
    def __init__(self, replica_id: int, initial_text: str = ""):
        self.replica_id = replica_id
        self.text = initial_text
        self.version = 0
        self.operations = []
    
    def apply_insert(self, position: int, char: str, user_id: str) -> Dict:
        self.text = self.text[:position] + char + self.text[position:]
        self.version += 1
        op = {"type": "insert", "pos": position, "char": char, "user": user_id, "v": self.version}
        self.operations.append(op)
        return op
    
    def apply_delete(self, position: int, user_id: str) -> Dict:
        if position < len(self.text):
            deleted = self.text[position]
            self.text = self.text[:position] + self.text[position+1:]
            self.version += 1
            op = {"type": "delete", "pos": position, "user": user_id, "v": self.version}
            self.operations.append(op)
            return op
        return {}

    def get_state(self) -> Dict:
        return {"text": self.text, "version": self.version}
