import re
from typing import List, Dict, Any, Optional

class RythmoEngine:
    """Moteur de règles §8.3 : segmentation des mots alignés en répliques cohérentes.
    Configurable via profils typographiques §2.4 / §16.3 (codes + seuils de calibrage)
    """

    SILENCE_MS = 500  # silence significatif en ms (défaut)
    MAX_DURATION_MS = 15000  # limite syntaxique / durée max par réplique (défaut)

    def __init__(self, profile: Optional[Dict[str, Any]] = None):
        # profile peut contenir {"codes": {...}, "thresholds": {...}, "conventions": {...}}
        profile = profile or {}
        thresholds = profile.get("thresholds") or {}
        codes = profile.get("codes") or {}
        self.profile = profile
        # Seuils de calibrage configurables par studio
        self.silence_ms = int(thresholds.get("silence_ms", self.SILENCE_MS))
        self.max_duration_ms = int(thresholds.get("max_duration_ms", self.MAX_DURATION_MS))
        # Codes typographiques du profil (pour application automatique lors de génération)
        # Normaliser les codes
        self.profile_codes = self._normalize_profile_codes(codes)

    @staticmethod
    def _normalize_profile_codes(codes: Dict[str, Any]) -> Dict[str, bool]:
        if not isinstance(codes, dict):
            return {}
        canonical_map = {
            "brackets": "crochets", "bracket_in": "crochets", "bracket_out": "crochets", "crochets": "crochets",
            "italic": "italique", "italique": "italique", "voix_off": "italique", "off": "italique",
            "uppercase": "majuscules", "majuscules": "majuscules", "cri": "majuscules", "caps": "majuscules",
            "parentheses": "parentheses", "parentheses_jeu": "parentheses", "indication_jeu": "parentheses", "jeu": "parentheses",
        }
        normalized = {}
        for k, v in codes.items():
            key = str(k).lower().strip()
            canon = canonical_map.get(key, key)
            if isinstance(v, bool):
                if v:
                    normalized[canon] = True
                else:
                    # False means disabled -> not included
                    pass
            elif isinstance(v, dict):
                if v.get("enabled"):
                    normalized[canon] = True
            elif isinstance(v, (int, float)):
                if bool(v):
                    normalized[canon] = True
            elif isinstance(v, str):
                if v.lower() in ("true", "1", "oui", "yes"):
                    normalized[canon] = True
            else:
                if bool(v):
                    normalized[canon] = True
        return normalized

    @staticmethod
    def split_text_by_syntax(text: str) -> list:
        # Découpage par ponctuation forte (., ;, ?, !, —) avec conservation
        # On conserve le séparateur dans le segment précédent
        parts = re.split(r"([\\.\\?\\!;\\—\\,])", text)
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
        if not words:
            return []
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
            if gap > self.silence_ms or w.get("speaker_id") != current_repo["speaker_id"]:
                # Ne pas ajouter de réplique vide (cas initial)
                if current_repo["text_parts"]:
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
            if (current_repo["end_ms"] - current_repo["start_ms"]) > self.max_duration_ms:
                # Attention : éviter de créer une réplique avec un seul mot si on vient de la créer
                # On finalise seulement si on a au moins 1 mot
                if current_repo["text_parts"]:
                    replicas.append(self._finalize_repo(current_repo))
                    # Réinitialiser avec le mot courant ? Mais on a déjà tout consommé.
                    # On crée un nouveau repo vide qui sera rempli au prochain tour
                    # Pour éviter de perdre le mot courant, on le conserve comme début du prochain
                    # Mais ici on vient d'ajouter le mot courant, donc on reset vide et le dernier mot a déjà été finalisé
                    # On recrée un repo vide pour le prochain mot (qui sera écrasé si pas de prochain)
                    current_repo = {
                        "text_parts": [],
                        "start_ms": w["end_ms"],
                        "end_ms": w["end_ms"],
                        "speaker_id": w.get("speaker_id"),
                    }
                    # Le prochain mot remplira current_repo
                    # Pour éviter un état vide, on ne garde pas le mot courant déjà finalisé
                    # On laisse current_repo vide, le prochain tour le remplira
                    # On doit s'assurer que si c'est le dernier mot, on ne crée pas de réplique vide
        if current_repo["text_parts"]:
            replicas.append(self._finalize_repo(current_repo))
        # Filtrer les répliques vides qui pourraient avoir été créées par la logique max_duration
        replicas = [r for r in replicas if r.get("text")]
        return replicas

    def _finalize_repo(self, repo: dict) -> dict:
        text = " ".join(repo["text_parts"]).strip()
        # Nettoyage syntaxique mineur
        text = re.sub(r"\\s+", " ", text)
        # Application des codes typographiques du profil §2.4
        # Si le profil définit des codes activés, ils sont appliqués à la réplique générée (première proposition)
        typo_codes = dict(self.profile_codes) if self.profile_codes else {}
        return {
            "text": text,
            "start_ms": repo["start_ms"],
            "end_ms": repo["end_ms"],
            "speaker_id": repo.get("speaker_id"),
            "duration_ms": repo["end_ms"] - repo["start_ms"],
            "has_breath_marker": repo["end_ms"] - repo["start_ms"] > self.max_duration_ms,  # simplifié
            "typo_codes": typo_codes,
        }

    def apply_profile_to_replica(self, replica: Dict[str, Any]) -> Dict[str, Any]:
        """Applique les codes du profil à une réplique existante (sans modifier le texte)"""
        replica = dict(replica)
        if self.profile_codes:
            replica["typo_codes"] = dict(self.profile_codes)
        return replica
