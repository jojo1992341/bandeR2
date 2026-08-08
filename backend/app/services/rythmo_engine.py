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

    # ── Synchronisation labiale §8.2.6, §11.4 ────────────────────────────────
    def refine_with_lip_sync(self, replicas: List[Dict[str, Any]], lip_curve: List[Dict[str, Any]], feature_enabled: bool = True, window_ms: int = 300) -> tuple:
        """Fiabilise le calage des crochets d'entrée/sortie sur gros plans via courbe d'activité labiale.
        lip_curve : liste de {timestamp_ms, opening, confidence, face_visible, is_close_up}
        Si feature_enabled=False ou courbe vide/peu visible, retourne les répliques inchangées.
        Ne modifie jamais le texte, seulement start/end (crochets).
        Retourne (replicas_refined, metrics).
        """
        if not feature_enabled or not lip_curve or not replicas:
            return replicas, {"feature_enabled": bool(feature_enabled), "refined_count": 0, "reason": "disabled_or_no_curve" if not feature_enabled or not lip_curve else "no_replicas"}

        # Vérifier visibilité globale
        visible_ratio = sum(1 for c in lip_curve if c.get("face_visible")) / len(lip_curve) if lip_curve else 0
        if visible_ratio < 0.15:
            return replicas, {"feature_enabled": True, "refined_count": 0, "reason": "face_not_visible_enough", "face_visible_ratio": visible_ratio}

        # Déléguer à LipSyncService pour la logique fine (évite duplication)
        try:
            from app.services.lip_sync_service import LipSyncService  # lazy
            # Créer un service factice sans DB pour la logique de raffinement
            class DummyDB:
                pass
            # On instancie le service avec un DB dummy mais on n'utilise que la logique de raffinement
            # Pour éviter dépendance DB, on recode ici une version légère
            pass
        except:
            pass

        # Logique de raffinement directe (sans DB)
        refined = []
        refined_count = 0
        total_adj = 0
        for rep in replicas:
            orig_start = int(rep.get("start_ms", 0))
            orig_end = int(rep.get("end_ms", 0))
            # Chercher ouverture près de orig_start
            new_start = self._find_lip_event(lip_curve, orig_start, window_ms, "opening")
            new_end = self._find_lip_event(lip_curve, orig_end, window_ms, "closing")
            if new_start is None:
                new_start = orig_start
            if new_end is None:
                new_end = orig_end
            # Garder start < end et durée minimale 200ms
            if new_end <= new_start:
                new_end = max(new_start + 200, orig_end)
                if new_end <= new_start:
                    new_start, new_end = orig_start, orig_end
            new_rep = dict(rep)
            # Ne jamais modifier le texte
            assert new_rep.get("text") == rep.get("text")
            new_rep["start_ms"] = int(new_start)
            new_rep["end_ms"] = int(new_end)
            new_rep["duration_ms"] = int(new_end - new_start)
            # Marquer le raffinement
            adj_start = int(new_start - orig_start)
            adj_end = int(new_end - orig_end)
            if adj_start != 0 or adj_end != 0:
                refined_count += 1
                total_adj += abs(adj_start) + abs(adj_end)
                new_rep["lip_sync_adjusted"] = True
                new_rep["lip_sync_adjustment"] = {"start_ms": adj_start, "end_ms": adj_end}
            else:
                new_rep["lip_sync_adjusted"] = False
            refined.append(new_rep)

        metrics = {
            "feature_enabled": True,
            "total": len(replicas),
            "refined_count": refined_count,
            "total_adjustment_ms": total_adj,
            "avg_adjustment_ms": (total_adj / refined_count) if refined_count else 0,
            "face_visible_ratio": visible_ratio,
            "window_ms": window_ms,
            "reason": "refined" if refined_count else "no_event_found",
        }
        return refined, metrics

    def _find_lip_event(self, curve: List[Dict[str, Any]], target_ms: int, window_ms: int, direction: str) -> Optional[int]:
        """Trouve l'événement labial le plus proche de target_ms dans window."""
        if not curve:
            return None
        candidates = []
        for i in range(1, len(curve)):
            prev = curve[i-1]
            curr = curve[i]
            if not curr.get("face_visible") or curr.get("confidence", 0) < 0.3:
                continue
            prev_o = prev.get("opening", 0)
            curr_o = curr.get("opening", 0)
            if direction == "opening":
                if prev_o < 0.3 and curr_o > 0.5:
                    ts = curr.get("timestamp_ms", 0)
                    if abs(ts - target_ms) <= window_ms:
                        candidates.append((abs(ts - target_ms), ts))
            elif direction == "closing":
                if prev_o > 0.5 and curr_o < 0.3:
                    ts = curr.get("timestamp_ms", 0)
                    if abs(ts - target_ms) <= window_ms:
                        candidates.append((abs(ts - target_ms), ts))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][1]

    def segment_words_with_lip_sync(self, words: List[Dict[str, Any]], lip_curve: Optional[List[Dict[str, Any]]] = None, feature_enabled: bool = None) -> List[Dict[str, Any]]:
        """Segmentation + raffinement labial optionnel (feature flag)."""
        # Segmentation de base
        replicas = self.segment_words(words)
        if lip_curve is None or feature_enabled is False:
            return replicas
        # Vérifier feature flag si non explicitement passé
        if feature_enabled is None:
            try:
                from app.core.config import get_settings
                feature_enabled = get_settings().is_feature_enabled("lip_sync")
            except:
                feature_enabled = False
        if not feature_enabled:
            return replicas
        refined, _ = self.refine_with_lip_sync(replicas, lip_curve, feature_enabled=True)
        return refined

