import re
import re
from typing import List, Dict, Any

class RythmoEngine:
    """Moteur de règles §8.3 : segmentation des mots alignés en répliques cohérentes."""

    SILENCE_MS = 500  # silence significatif en ms
    MAX_DURATION_MS = 15000  # limite syntaxique / durée max par réplique

    @staticmethod
    def split_text_by_syntax(text: str) -> list:
        # Découpage par ponctuation forte (., ;, ?, !, —) avec conservation
        # On conserve le séparateur dans le segment précédent
        parts = re.split(r"([\.\?\!;\—\,])", text)
        segments = []
        current = ""
        for part in parts:
            current += part
            if part in (".", "?", "!", ";", "—"):
                segments.append(current.strip())
                current = ""
        if current.strip():
            segments.append(current.strip())
        return segments

    def segment_words(self, words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # words = list of {text, start_ms, end_ms, speaker_id, ...}
        replicas = []
        current_repo = {
            "text_parts": [],
            "start_ms": words[0]["start_ms"] if words else 0,
            "end_ms": words[0]["end_ms"] if words else 0,
            "speaker_id": words[0]["speaker_id"] if words else None,
        }
        for i, w in enumerate(words):
            prev = words[i-1] if i > 0 else w
            gap = w["start_ms"] - prev["end_ms"]
            # Déclencher nouvelle réplique si silence > seuil, changement de locuteur, ou limite syntaxique
            if gap > self.SILENCE_MS or w.get("speaker_id") != current_repo["speaker_id"]:
                replicas.append(self._finalize_repo(current_repo))
                current_repo = {
                    "text_parts": [w["text"]],
                    "start_ms": w["start_ms"],
                    "end_ms": w["end_ms"],
                    "speaker_id": w.get("speaker_id"),
                }
            else:
                current_repo["text_parts"].append(w["text"])
                current_repo["end_ms"] = w["end_ms"]
            # Déclencher aussi si durée > limite (synthèse syntaxique approximative)
            if (current_repo["end_ms"] - current_repo["start_ms"]) > self.MAX_DURATION_MS:
                replicas.append(self._finalize_repo(current_repo))
                current_repo = {
                    "text_parts": [w["text"]],
                    "start_ms": w["start_ms"],
                    "end_ms": w["end_ms"],
                    "speaker_id": w.get("speaker_id"),
                }
        if current_repo["text_parts"]:
            replicas.append(self._finalize_repo(current_repo))
        return replicas

    def _finalize_repo(self, repo: dict) -> dict:
        text = " ".join(repo["text_parts"]).strip()
        # Nettoyage syntaxique mineur
        text = re.sub(r"\s+", " ", text)
        return {
            "text": text,
            "start_ms": repo["start_ms"],
            "end_ms": repo["end_ms"],
            "speaker_id": repo.get("speaker_id"),
            "duration_ms": repo["end_ms"] - repo["start_ms"],
            "has_breath_marker": repo["end_ms"] - repo["start_ms"] > self.MAX_DURATION_MS,  # simplifié
        }
