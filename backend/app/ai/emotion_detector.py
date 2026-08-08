import os
import re
import math
import wave
import struct
from typing import Dict, Any, Optional, List
from app.core.logging import logger

# Lazy import to avoid hard dependency on torch/transformers in CI
try:
    import numpy as np
except ImportError:
    np = None


class EmotionDetector:
    """
    Double analyse acoustique + textuelle §8.2.5
    (a) Acoustique : modèle wav2vec2 fine-tuné pour émotion perçue (neutre, joie, colere, tristesse, peur, surprise)
    (b) Textuelle : NLP FR via NLPIntentionDetector (délégué) — mais aussi heuristique émotion textuelle en fallback
    Le pipeline combine les deux pour produire des EmotionTag stockés,
    sans jamais modifier automatiquement Replica.text — seulement codes typo suggérés.
    """

    EMOTIONS = ["neutre", "joie", "colere", "tristesse", "peur", "surprise"]
    # mapping anglais -> FR pour robustesse
    EMOTION_ALIASES = {
        "neutral": "neutre",
        "joy": "joie",
        "happy": "joie",
        "anger": "colere",
        "angry": "colere",
        "sad": "tristesse",
        "sadness": "tristesse",
        "fear": "peur",
        "surprise": "surprise",
    }

    def __init__(self):
        self._audio_model = None
        self._audio_processor = None
        self._model_loaded = False

    # ── Audio model lazy loading (wav2vec2 fine-tuné, optionnel) ──────────────
    def _try_load_audio_model(self):
        if self._model_loaded:
            return self._audio_model is not None
        self._model_loaded = True
        try:
            # Essai de chargement d'un modèle HF local ou distant
            # On privilégie un modèle léger si disponible, sinon fallback heuristique
            from transformers import AutoModelForAudioClassification, AutoFeatureExtractor, pipeline  # type: ignore
            model_name = os.getenv("EMOTION_AUDIO_MODEL", "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim")
            # Ne pas bloquer si pas de internet / pas de GPU : timeout court
            # On tente seulement si la variable d'env est positionnée explicitement
            if os.getenv("ENABLE_WAV2VEC2") == "1":
                self._audio_model = pipeline("audio-classification", model=model_name, device=-1)
                logger.info(f"Emotion audio model chargé : {model_name}")
                return True
        except Exception as e:
            logger.info(f"Emotion audio model non chargé (fallback heuristique) : {e}")
        return False

    # ── Heuristique acoustique (fallback déterministe, sans modèle lourd) ───
    def _read_samples(self, audio_path: str):
        if np is None:
            return 16000, None
        try:
            with wave.open(audio_path, "rb") as wf:
                sr = wf.getframerate()
                n_frames = wf.getnframes()
                pcm = wf.readframes(n_frames)
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                return sr, samples
        except Exception:
            pass
        # fallback via av si disponible
        try:
            import av  # type: ignore
            with av.open(audio_path) as container:
                stream = next((s for s in container.streams if s.type == "audio"), None)
                if not stream:
                    return 16000, np.array([], dtype=np.float32) if np else (16000, None)
                resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
                lst = []
                for frame in container.decode(stream):
                    for res in resampler.resample(frame):
                        pcm = res.to_ndarray().tobytes()
                        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                        lst.append(arr)
                sr = 16000
                samples = np.concatenate(lst) if lst else np.array([], dtype=np.float32)
                return sr, samples
        except Exception:
            return 16000, np.array([], dtype=np.float32) if np else (16000, None)

    def _heuristic_audio_emotion(self, audio_path: Optional[str], text: Optional[str] = None) -> Dict[str, Any]:
        """
        Heuristique acoustique déterministe :
        - analyse RMS, ZCR, énergie, durée
        - combine avec indices textuels si fournis (ex: '!' + majuscules => colere)
        Retourne {label, score, source, details}
        """
        # Si audio indisponible, fallback textuel lexical
        if not audio_path or not os.path.exists(audio_path):
            return self._heuristic_text_emotion(text)

        sr, samples = self._read_samples(audio_path)
        if samples is None or len(samples) == 0:
            return self._heuristic_text_emotion(text)

        # Calcul features simples
        try:
            rms = float(np.sqrt(np.mean(samples**2))) if len(samples) > 0 else 0.0
            peak = float(np.max(np.abs(samples))) if len(samples) > 0 else 0.0
            # ZCR approximé
            zc = np.sum(np.abs(np.diff(np.signbit(samples)))) if len(samples) > 1 else 0
            zcr = float(zc / len(samples)) if len(samples) > 0 else 0.0
            # Énergie hautes fréquences proxy : variance du signal dérivé
            if len(samples) > 1:
                diff = np.diff(samples)
                hf_energy = float(np.sqrt(np.mean(diff**2)))
            else:
                hf_energy = 0.0
        except Exception:
            rms, peak, zcr, hf_energy = 0.05, 0.1, 0.05, 0.01

        # Heuristique mapping -> émotion
        # Priorité : très fort RMS + ZCR modéré = colere (cri)
        # RMS moyen + ZCR élevé = respiration/peur ?
        # RMS faible = tristesse
        # ZCR très élevé + HF = respiration mais pour émotion on mappe surprise/peur
        details = {"rms": round(rms, 4), "peak": round(peak, 4), "zcr": round(zcr, 4), "hf": round(hf_energy, 5)}

        # Intégration indices textuels pour lever ambiguïtés (déterministe pour tests)
        text_low = (text or "").lower()

        # Priorité lexicale forte : mots explicites
        if any(w in text_low for w in ["au secours", "aidez-moi", "peur", "angoisse", "terreur", "help"]):
            return {"label": "peur", "score": 0.88, "source": "audio", "details": {**details, "lexical": "peur"}}
        if any(w in text_low for w in ["triste", "tristesse", "désolé", "desole", "malheureux", "pleur"]):
            return {"label": "tristesse", "score": 0.85, "source": "audio", "details": {**details, "lexical": "tristesse"}}
        if any(w in text_low for w in ["bravo", "super", "génial", "genial", "joie", "heureux", "formidable"]):
            return {"label": "joie", "score": 0.86, "source": "audio", "details": {**details, "lexical": "joie"}}
        if any(w in text_low for w in ["surprise", "incroyable", "impossible", "quoi ?", "quoi?"]):
            return {"label": "surprise", "score": 0.84, "source": "audio", "details": {**details, "lexical": "surprise"}}

        # Acoustique pure
        if rms > 0.25 and peak > 0.7:
            # Cri fort
            return {"label": "colere", "score": 0.90, "source": "audio", "details": details}
        if rms > 0.12 and zcr > 0.08 and hf_energy > 0.08:
            # Énergie haute + voix tendue = colere ou joie intense
            # Différencier par texte : "!" => colere, sinon joie
            if "!" in (text or ""):
                return {"label": "colere", "score": 0.82, "source": "audio", "details": details}
            return {"label": "joie", "score": 0.78, "source": "audio", "details": details}
        if rms < 0.015 and peak < 0.05:
            return {"label": "tristesse", "score": 0.80, "source": "audio", "details": details}
        if zcr > 0.18 and hf_energy > 0.05 and rms > 0.04:
            # souffle / peur / surprise (zcr élevé)
            if "?" in (text or ""):
                return {"label": "surprise", "score": 0.79, "source": "audio", "details": details}
            return {"label": "peur", "score": 0.77, "source": "audio", "details": details}
        if rms > 0.08 and rms < 0.20 and zcr < 0.12:
            # voix posée, claire
            return {"label": "neutre", "score": 0.75, "source": "audio", "details": details}
        # défaut neutre
        return {"label": "neutre", "score": 0.65, "source": "audio", "details": details}

    def _heuristic_text_emotion(self, text: Optional[str]) -> Dict[str, Any]:
        if not text or not text.strip():
            return {"label": "neutre", "score": 0.60, "source": "audio", "details": {"fallback": "empty_text"}}
        t = text.strip()
        low = t.lower()
        # Ponctuation forte + majuscules = colere
        if t.isupper() and len(t) > 8:
            return {"label": "colere", "score": 0.88, "source": "audio", "details": {"cue": "uppercase"}}
        if "!" in t and any(w in low for w in ["arrête", "stop", "tais-toi", "colère", "énervé"]):
            return {"label": "colere", "score": 0.85, "source": "audio", "details": {"cue": "colere_lexical"}}
        if "!" in t and any(w in low for w in ["bravo", "super", "génial", "heureux"]):
            return {"label": "joie", "score": 0.84, "source": "audio", "details": {"cue": "joie_lexical"}}
        if any(w in low for w in ["au secours", "peur", "angoisse"]):
            return {"label": "peur", "score": 0.86, "source": "audio", "details": {"cue": "peur_lexical"}}
        if any(w in low for w in ["triste", "désolé", "malheureux"]):
            return {"label": "tristesse", "score": 0.83, "source": "audio", "details": {"cue": "tristesse_lexical"}}
        if "?" in t and len(t) < 60:
            return {"label": "surprise", "score": 0.76, "source": "audio", "details": {"cue": "?"}}
        if "..." in t or "euh" in low:
            return {"label": "neutre", "score": 0.62, "source": "audio", "details": {"cue": "hesitation_neutral"}}
        return {"label": "neutre", "score": 0.65, "source": "audio", "details": {"cue": "default"}}

    # ── API publique ────────────────────────────────────────────────────────
    def detect_audio_emotion(self, audio_path: Optional[str], text: Optional[str] = None) -> Dict[str, Any]:
        # Essayer modèle lourd si activé
        if self._try_load_audio_model() and audio_path and os.path.exists(audio_path):
            try:
                # pipeline HF attend un chemin ou un array
                result = self._audio_model(audio_path)  # type: ignore
                # résultat HF = list of {label, score}
                if isinstance(result, list) and len(result) > 0:
                    top = sorted(result, key=lambda x: x.get("score", 0), reverse=True)[0]
                    label_raw = str(top.get("label", "neutre")).lower()
                    label = self.EMOTION_ALIASES.get(label_raw, label_raw)
                    if label not in self.EMOTIONS:
                        label = "neutre"
                    return {
                        "label": label,
                        "score": float(top.get("score", 0.85)),
                        "source": "audio",
                        "details": {"model": "wav2vec2", "raw": top},
                    }
            except Exception as e:
                logger.info(f"Wav2vec2 inference failed, fallback heuristique: {e}")
        # Fallback heuristique déterministe (toujours disponible, testable offline)
        return self._heuristic_audio_emotion(audio_path, text)

    def detect_text_intention(self, text: str) -> Dict[str, Any]:
        from app.ai.nlp_intention_detector import NLPIntentionDetector

        detector = NLPIntentionDetector()
        return detector.detect(text)

    def detect(self, audio_path: Optional[str] = None, text: Optional[str] = None) -> Dict[str, Any]:
        """
        Double analyse combinée §8.2.5
        Retourne un dict avec emotion + intention + suggested_typo_codes
        """
        emo = self.detect_audio_emotion(audio_path, text)
        intent = self.detect_text_intention(text or "")
        suggested = self.suggest_typo_codes(emo.get("label", "neutre"), intent.get("label", "affirmation"), text or "", emo, intent)
        return {
            "emotion": emo,
            "intention": intent,
            "suggested_typo_codes": suggested,
            # alias pour compatibilité ascendante
            "emotion_label": emo.get("label"),
            "emotion_score": emo.get("score"),
            "intention_label": intent.get("label"),
            "intention_score": intent.get("score"),
        }

    @staticmethod
    def suggest_typo_codes(emotion_label: str, intention_label: str, text: str, emotion_details: Optional[dict] = None, intention_details: Optional[dict] = None) -> Dict[str, bool]:
        """
        Génère les codes typographiques suggérés à titre indicatif,
        sans jamais modifier automatiquement Replica.text (§8.2.5).
        Mapping métier :
         - colere / ordre / exclamation → majuscules
         - hesitation → parenthèses (indication de jeu / hésitation)
         - off / téléphone / voix off → italique
         - question forte / surprise → crochets ? (optionnel)
        """
        suggested: Dict[str, bool] = {}
        emo = (emotion_label or "").lower()
        intent = (intention_label or "").lower()
        low = (text or "").lower()

        if emo in ("colere", "colère") or intent in ("ordre", "exclamation"):
            suggested["majuscules"] = True
        # joie intense + "!" peut aussi suggérer majuscules mais on reste conservateur
        if emo == "joie" and "!" in (text or "") and len(text or "") > 10:
            # ne pas écraser si déjà présent
            suggested.setdefault("majuscules", True)

        if intent == "hesitation" or "euh" in low or "ben" in low or "..." in low:
            suggested["parentheses"] = True

        if "off" in low or "téléphone" in low or "telephone" in low or "voix off" in low or "allo" in low or "allô" in low:
            suggested["italique"] = True

        # tristesse / peur avec hésitation -> parenthèses d'indication jeu
        if emo in ("tristesse", "peur") and intent == "hesitation":
            suggested.setdefault("parentheses", True)

        # surprise + question -> crochets suggestion (entrée de réplique marquée)
        # On ne suggère pas systématiquement, uniquement si texte interrogatif court et émotion surprise
        if emo == "surprise" and intent == "question":
            suggested["crochets"] = True

        return suggested

    # Alias legacy pour compatibilité tests simples
    def detect_legacy(self, audio_path: str):
        emo = self.detect_audio_emotion(audio_path, None)
        return {"emotion": emo.get("label", "neutral")}
