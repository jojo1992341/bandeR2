import uuid
import hashlib
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models import Studio, Project, MediaAsset, AnonymizedCorrection
from app.core.logging import logger

class FeedbackService:
    """
    §8.5 — Feedback loop anonymisé
    Journalise les corrections manuelles de façon anonymisée si le studio a consenti,
    pour constituer un corpus d'entraînement des modèles heuristiques (prosodie, émotion).
    Ne réentraîne jamais les modèles de fondation tiers (Whisper, pyannote) hors licence.
    """

    # Cibles heuristiques autorisées — jamais les fondations
    ALLOWED_HEURISTIC_TARGETS = {"prosody", "emotion", "diarization", "silence", "typography"}
    FORBIDDEN_TARGETS = {"whisper", "pyannote", "wav2vec2", "whisperx", "foundation"}

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _hash(value: str) -> str:
        if not value:
            return ""
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _hash_studio(studio_id: uuid.UUID) -> str:
        return hashlib.sha256(str(studio_id).encode()).hexdigest()[:16]

    @staticmethod
    def _hash_user(user_id: Optional[uuid.UUID]) -> str:
        if not user_id:
            return ""
        return hashlib.sha256(str(user_id).encode()).hexdigest()[:16]

    def has_consent(self, studio_id: uuid.UUID) -> bool:
        """Vérifie si le studio a explicitement consenti (§8.5)."""
        studio = self.db.query(Studio).filter(Studio.id == studio_id).first()
        if not studio:
            return False
        settings = getattr(studio, "feedback_settings", None) or {}
        # Le consentement doit être explicite : enabled == True
        return bool(settings.get("enabled") is True)

    def set_consent(self, studio_id: uuid.UUID, enabled: bool, consented_by: Optional[uuid.UUID] = None) -> dict:
        """Définit le consentement du studio (admin uniquement)."""
        from datetime import datetime, timezone
        studio = self.db.query(Studio).filter(Studio.id == studio_id).first()
        if not studio:
            raise ValueError("Studio non trouvé")
        current = dict(getattr(studio, "feedback_settings", None) or {})
        current["enabled"] = bool(enabled)
        if enabled:
            current["consented_at"] = datetime.now(timezone.utc).isoformat()
            current["consented_by"] = str(consented_by) if consented_by else None
            current["version"] = int(current.get("version", 0)) + 1 if current.get("version") else 1
        else:
            current["consented_at"] = None
            current["consented_by"] = None
            # On garde la version
        studio.feedback_settings = current
        self.db.commit()
        self.db.refresh(studio)
        return current

    def get_consent(self, studio_id: uuid.UUID) -> dict:
        studio = self.db.query(Studio).filter(Studio.id == studio_id).first()
        if not studio:
            return {"enabled": False}
        return dict(getattr(studio, "feedback_settings", None) or {"enabled": False})

    def _validate_heuristic_target(self, target: str) -> str:
        target = (target or "prosody").lower()
        if target in self.FORBIDDEN_TARGETS:
            raise ValueError(f"Réentraînement du modèle de fondation '{target}' interdit hors licence — seuls les heuristiques {self.ALLOWED_HEURISTIC_TARGETS} sont autorisés")
        if target not in self.ALLOWED_HEURISTIC_TARGETS:
            # Par défaut, autoriser prosody/emotion, mais logger
            logger.warning(f"Heuristic target '{target}' non listé, fallback prosody")
            return "prosody"
        return target

    def log_correction(
        self,
        studio_id: uuid.UUID,
        correction_type: str,
        project_id: Optional[uuid.UUID] = None,
        media_id: Optional[uuid.UUID] = None,
        original_data: Optional[dict] = None,
        corrected_data: Optional[dict] = None,
        heuristic_target: str = "prosody",
        user_id: Optional[uuid.UUID] = None,
        model_version: str = "heuristic-v1",
    ) -> Optional[AnonymizedCorrection]:
        """
        Journalise une correction de façon anonymisée, uniquement si consentement.
        Retourne l'enregistrement ou None si pas de consentement.
        Anonymise : hashes, pas d'email, pas de texte brut complet (seulement deltas).
        """
        if not self.has_consent(studio_id):
            logger.debug(f"Studio {studio_id} n'a pas consenti — pas de journalisation")
            return None

        # Valider que l'on n'entraîne pas un modèle de fondation
        heuristic_target = self._validate_heuristic_target(heuristic_target)

        # Anonymisation : ne jamais stocker de PII
        # Hacher les IDs, ne pas stocker le texte brut complet, seulement des métriques
        anon_studio_hash = self._hash_studio(studio_id)
        anon_user_hash = self._hash_user(user_id)

        # Construire correction_data anonymisée
        # Pour chaque type, on extrait seulement les métriques exploitables
        correction_data = {}
        original_hash = ""
        corrected_hash = ""

        if correction_type == "word_realign":
            # original/corrected : {word_id, start_ms, end_ms, text_length}
            # On anonymise word_id et on ne stocke pas le texte brut, seulement le delta
            orig = original_data or {}
            corr = corrected_data or {}
            # Hacher l'ID du mot
            orig_hash = self._hash(str(orig.get("word_id", "")))
            corr_hash = self._hash(str(corr.get("word_id", "")))
            original_hash = orig_hash
            corrected_hash = corr_hash
            correction_data = {
                "word_hash": orig_hash,  # anonymisé
                "start_delta_ms": int(corr.get("start_ms", 0)) - int(orig.get("start_ms", 0)),
                "end_delta_ms": int(corr.get("end_ms", 0)) - int(orig.get("end_ms", 0)),
                "original_duration_ms": int(orig.get("end_ms", 0)) - int(orig.get("start_ms", 0)),
                "corrected_duration_ms": int(corr.get("end_ms", 0)) - int(corr.get("start_ms", 0)),
                "text_length": orig.get("text_length") or len(str(orig.get("text", ""))),
                "confidence_before": orig.get("confidence_score"),
            }
        elif correction_type == "speaker_correction":
            orig = original_data or {}
            corr = corrected_data or {}
            orig_spk = str(orig.get("speaker_id", ""))
            corr_spk = str(corr.get("speaker_id", ""))
            original_hash = self._hash(orig_spk)
            corrected_hash = self._hash(corr_spk)
            correction_data = {
                "original_speaker_hash": original_hash,
                "corrected_speaker_hash": corrected_hash,
                "num_words_affected": corr.get("num_words_affected", 1),
                "original_label_hash": self._hash(str(orig.get("label", ""))),
                "corrected_label_hash": self._hash(str(corr.get("label", ""))),
            }
        elif correction_type == "typo_code_change":
            orig = original_data or {}
            corr = corrected_data or {}
            # Hacher les codes typo comme JSON
            import json
            orig_json = json.dumps(orig.get("typo_codes", {}), sort_keys=True)
            corr_json = json.dumps(corr.get("typo_codes", {}), sort_keys=True)
            original_hash = self._hash(orig_json)
            corrected_hash = self._hash(corr_json)
            orig_codes = orig.get("typo_codes", {}) or {}
            corr_codes = corr.get("typo_codes", {}) or {}
            added = {k: v for k, v in corr_codes.items() if k not in orig_codes or orig_codes[k] != v}
            removed = {k: v for k, v in orig_codes.items() if k not in corr_codes or orig_codes[k] != corr_codes[k]}
            correction_data = {
                "original_typo_hash": original_hash,
                "corrected_typo_hash": corrected_hash,
                "added_codes": added,
                "removed_codes": removed,
                "original_codes": {k: bool(v) for k, v in orig_codes.items()},  # anonymisé bool
                "corrected_codes": {k: bool(v) for k, v in corr_codes.items()},
            }
        else:
            # Générique
            import json
            original_hash = self._hash(str(original_data))
            corrected_hash = self._hash(str(corrected_data))
            correction_data = {
                "original": {k: v for k, v in (original_data or {}).items() if k not in ("text", "email", "user_id")},
                "corrected": {k: v for k, v in (corrected_data or {}).items() if k not in ("text", "email", "user_id")},
            }

        # Créer l'enregistrement
        entry = AnonymizedCorrection(
            id=uuid.uuid4(),
            studio_id=studio_id,
            project_id=project_id,
            media_id=media_id,
            correction_type=correction_type,
            correction_data=correction_data,
            original_hash=original_hash,
            corrected_hash=corrected_hash,
            heuristic_target=heuristic_target,
            model_version=model_version,
            is_anonymized=True,
            consent_given=True,
            anonymized_studio_hash=anon_studio_hash,
            anonymized_user_hash=anon_user_hash,
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        logger.info(f"Correction anonymisée journalisée: {correction_type} pour studio {anon_studio_hash} -> {heuristic_target}")
        return entry

    def list_corrections(self, studio_id: uuid.UUID, limit: int = 100, offset: int = 0, correction_type: Optional[str] = None):
        q = self.db.query(AnonymizedCorrection).filter(AnonymizedCorrection.studio_id == studio_id)
        if correction_type:
            q = q.filter(AnonymizedCorrection.correction_type == correction_type)
        q = q.order_by(AnonymizedCorrection.created_at.desc()).offset(offset).limit(limit)
        return q.all()

    def stats_for_training(self, studio_id: uuid.UUID) -> dict:
        """Statistiques exploitables pour l'entraînement des heuristiques."""
        from sqlalchemy import func
        total = self.db.query(AnonymizedCorrection).filter(AnonymizedCorrection.studio_id == studio_id).count()
        by_type = self.db.query(AnonymizedCorrection.correction_type, func.count(AnonymizedCorrection.id)).filter(AnonymizedCorrection.studio_id == studio_id).group_by(AnonymizedCorrection.correction_type).all()
        by_target = self.db.query(AnonymizedCorrection.heuristic_target, func.count(AnonymizedCorrection.id)).filter(AnonymizedCorrection.studio_id == studio_id).group_by(AnonymizedCorrection.heuristic_target).all()
        return {
            "total": total,
            "by_type": {k: v for k, v in by_type},
            "by_heuristic": {k: v for k, v in by_target},
            "is_anonymized": True,
            "consent_given": self.has_consent(studio_id),
        }
