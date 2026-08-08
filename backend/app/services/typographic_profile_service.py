import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models import TypographicProfile, Studio
from app.core.logging import logger

# Valeurs par défaut §2.4 & §8.3
DEFAULT_CODES = {
    "crochets": True,
    "italique": True,
    "majuscules": True,
    "parentheses": True,
}

DEFAULT_THRESHOLDS = {
    "silence_ms": 500,
    "max_duration_ms": 15000,
    "syllable_rate_min": 5.0,
    "syllable_rate_max": 7.0,
    "confidence_threshold": 0.75,
}

DEFAULT_CONVENTIONS = {
    "italique_off": True,
    "majuscules_cri": True,
    "parentheses_jeu": True,
}

def normalize_codes(raw: Optional[dict]) -> Dict[str, Any]:
    if raw is None:
        return dict(DEFAULT_CODES)
    if not isinstance(raw, dict):
        raise ValueError("codes doit être un objet JSON")
    normalized = {}
    for k, v in raw.items():
        key = str(k).lower().strip()
        # canonical mapping
        canonical_map = {
            "brackets": "crochets", "bracket_in": "crochets", "bracket_out": "crochets", "crochets": "crochets",
            "italic": "italique", "italique": "italique", "voix_off": "italique", "off": "italique",
            "uppercase": "majuscules", "majuscules": "majuscules", "cri": "majuscules", "caps": "majuscules",
            "parentheses": "parentheses", "parentheses_jeu": "parentheses", "indication_jeu": "parentheses", "jeu": "parentheses",
        }
        canon = canonical_map.get(key, key)
        if isinstance(v, bool):
            normalized[canon] = v
        elif isinstance(v, str):
            normalized[canon] = v.lower() in ("true", "1", "oui", "yes")
        elif isinstance(v, (int, float)):
            normalized[canon] = bool(v)
        elif isinstance(v, dict):
            # support complexe {enabled: true, style: ...}
            enabled = v.get("enabled", True)
            normalized[canon] = bool(enabled)
        else:
            normalized[canon] = bool(v)
    # Compléter avec défauts pour les codes manquants? Non, on laisse tel quel, l'engine fera fallback
    return normalized

def normalize_thresholds(raw: Optional[dict]) -> Dict[str, Any]:
    if raw is None:
        return dict(DEFAULT_THRESHOLDS)
    if not isinstance(raw, dict):
        raise ValueError("thresholds doit être un objet JSON")
    normalized = {}
    for k, v in raw.items():
        key = str(k).strip()
        try:
            # Convertir en nombre selon clé
            if key in ("silence_ms", "max_duration_ms"):
                normalized[key] = int(v)
            elif key in ("syllable_rate_min", "syllable_rate_max", "confidence_threshold"):
                normalized[key] = float(v)
            else:
                # garder tel quel, tentative de conversion
                if isinstance(v, str):
                    try:
                        normalized[key] = int(v) if v.isdigit() else float(v)
                    except:
                        normalized[key] = v
                else:
                    normalized[key] = v
        except Exception:
            normalized[key] = v
    return normalized

def validate_profile_payload(payload: dict) -> dict:
    """
    Valide et normalise un payload de profil
    Payload attendu: {name, codes, thresholds, conventions, description, is_default}
    """
    if not isinstance(payload, dict):
        raise ValueError("Payload doit être un objet JSON")
    name = payload.get("name")
    if not name or not str(name).strip():
        raise ValueError("name est requis")
    name = str(name).strip()
    if len(name) > 100:
        raise ValueError("name trop long (max 100)")
    codes = normalize_codes(payload.get("codes"))
    thresholds = normalize_thresholds(payload.get("thresholds"))
    conventions = payload.get("conventions") or {}
    if not isinstance(conventions, dict):
        raise ValueError("conventions doit être un objet JSON")
    description = payload.get("description")
    if description is not None:
        description = str(description).strip()
        if len(description) > 500:
            description = description[:500]
    is_default = bool(payload.get("is_default", False))
    return {
        "name": name,
        "description": description,
        "codes": codes,
        "thresholds": thresholds,
        "conventions": conventions,
        "is_default": is_default,
    }

class TypographicProfileService:
    def __init__(self, db: Session):
        self.db = db

    def list_by_studio(self, studio_id: uuid.UUID) -> List[TypographicProfile]:
        return self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id).order_by(TypographicProfile.created_at).all()

    def get_by_id(self, studio_id: uuid.UUID, profile_id: uuid.UUID) -> Optional[TypographicProfile]:
        return self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id, TypographicProfile.id == profile_id).first()

    def get_default(self, studio_id: uuid.UUID) -> Optional[TypographicProfile]:
        # Chercher is_default True, sinon premier
        prof = self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id, TypographicProfile.is_default == True).first()
        if prof:
            return prof
        return self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id).order_by(TypographicProfile.created_at).first()

    def get_effective_profile(self, studio_id: uuid.UUID, profile_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
        """
        Retourne le profil effectif (codes+thresholds) à utiliser pour la génération.
        Si profile_id fourni, utilise celui-ci sinon default/si aucun, retourne DEFAULTS
        """
        if profile_id:
            prof = self.get_by_id(studio_id, profile_id)
            if prof:
                return {
                    "id": str(prof.id),
                    "name": prof.name,
                    "codes": prof.codes or dict(DEFAULT_CODES),
                    "thresholds": {**DEFAULT_THRESHOLDS, **(prof.thresholds or {})},
                    "conventions": prof.conventions or dict(DEFAULT_CONVENTIONS),
                }
        default_prof = self.get_default(studio_id)
        if default_prof:
            return {
                "id": str(default_prof.id),
                "name": default_prof.name,
                "codes": default_prof.codes or dict(DEFAULT_CODES),
                "thresholds": {**DEFAULT_THRESHOLDS, **(default_prof.thresholds or {})},
                "conventions": default_prof.conventions or dict(DEFAULT_CONVENTIONS),
            }
        # Aucun profil custom : retourner défauts globaux + legacy custom_typographic_profiles si présent
        studio = self.db.query(Studio).filter(Studio.id == studio_id).first()
        if studio and studio.custom_typographic_profiles:
            legacy = studio.custom_typographic_profiles
            # legacy peut contenir codes/thresholds
            codes = legacy.get("codes") or legacy.get("typo_codes") or dict(DEFAULT_CODES)
            thresholds = legacy.get("thresholds") or legacy.get("seuils") or dict(DEFAULT_THRESHOLDS)
            return {
                "id": None,
                "name": "legacy",
                "codes": normalize_codes(codes),
                "thresholds": {**DEFAULT_THRESHOLDS, **normalize_thresholds(thresholds)},
                "conventions": dict(DEFAULT_CONVENTIONS),
            }
        return {
            "id": None,
            "name": "default",
            "codes": dict(DEFAULT_CODES),
            "thresholds": dict(DEFAULT_THRESHOLDS),
            "conventions": dict(DEFAULT_CONVENTIONS),
        }

    def create(self, studio_id: uuid.UUID, payload: dict) -> TypographicProfile:
        data = validate_profile_payload(payload)
        # Vérifier unicité name
        existing = self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id, TypographicProfile.name == data["name"]).first()
        if existing:
            raise ValueError(f"Un profil nommé '{data['name']}' existe déjà pour ce studio")
        # Si is_default True, décocher les autres
        if data["is_default"]:
            self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id).update({"is_default": False})
        prof = TypographicProfile(
            id=uuid.uuid4(),
            studio_id=studio_id,
            name=data["name"],
            description=data["description"],
            codes=data["codes"],
            thresholds=data["thresholds"],
            conventions=data["conventions"],
            is_default=data["is_default"],
        )
        self.db.add(prof)
        self.db.commit()
        self.db.refresh(prof)
        # Si c'est le premier profil du studio, le marquer comme défaut
        count = self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id).count()
        if count == 1 and not prof.is_default:
            prof.is_default = True
            self.db.commit()
            self.db.refresh(prof)
        return prof

    def update(self, studio_id: uuid.UUID, profile_id: uuid.UUID, payload: dict) -> TypographicProfile:
        prof = self.get_by_id(studio_id, profile_id)
        if not prof:
            raise ValueError("Profil non trouvé")
        # Validation partielle
        if "name" in payload:
            new_name = str(payload["name"]).strip()
            if not new_name:
                raise ValueError("name ne peut être vide")
            # Vérifier conflit
            conflict = self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id, TypographicProfile.name == new_name, TypographicProfile.id != profile_id).first()
            if conflict:
                raise ValueError(f"Un autre profil nommé '{new_name}' existe déjà")
            prof.name = new_name
        if "description" in payload:
            desc = payload["description"]
            prof.description = str(desc).strip()[:500] if desc is not None else None
        if "codes" in payload:
            prof.codes = normalize_codes(payload["codes"])
        if "thresholds" in payload:
            # Merger avec existant
            existing_thr = prof.thresholds or {}
            new_thr = normalize_thresholds(payload["thresholds"])
            merged = {**existing_thr, **new_thr}
            prof.thresholds = merged
        if "conventions" in payload:
            if not isinstance(payload["conventions"], dict):
                raise ValueError("conventions doit être un objet")
            prof.conventions = payload["conventions"]
        if "is_default" in payload:
            is_def = bool(payload["is_default"])
            if is_def:
                self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id, TypographicProfile.id != profile_id).update({"is_default": False})
            prof.is_default = is_def
        self.db.commit()
        self.db.refresh(prof)
        return prof

    def delete(self, studio_id: uuid.UUID, profile_id: uuid.UUID):
        prof = self.get_by_id(studio_id, profile_id)
        if not prof:
            raise ValueError("Profil non trouvé")
        was_default = prof.is_default
        self.db.delete(prof)
        self.db.commit()
        if was_default:
            # Promouvoir le plus ancien comme nouveau défaut si existe
            remaining = self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id).order_by(TypographicProfile.created_at).first()
            if remaining:
                remaining.is_default = True
                self.db.commit()

    def bulk_upsert(self, studio_id: uuid.UUID, profiles_payload: List[dict]) -> List[TypographicProfile]:
        """
        PATCH collection : crée ou met à jour plusieurs profils
        Si un profil avec même name existe, on update, sinon create
        """
        result = []
        for payload in profiles_payload:
            if not isinstance(payload, dict):
                continue
            name = payload.get("name")
            if not name:
                continue
            existing = self.db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id, TypographicProfile.name == str(name).strip()).first()
            if existing:
                # update
                upd = self.update(studio_id, existing.id, payload)
                result.append(upd)
            else:
                # create
                try:
                    new_prof = self.create(studio_id, payload)
                    result.append(new_prof)
                except ValueError as e:
                    # ignorer doublons
                    logger.warning(f"bulk_upsert skip {name}: {e}")
        return result

    @staticmethod
    def serialize(prof: TypographicProfile) -> Dict[str, Any]:
        return {
            "id": str(prof.id),
            "studio_id": str(prof.studio_id),
            "name": prof.name,
            "description": prof.description,
            "codes": prof.codes or {},
            "thresholds": prof.thresholds or {},
            "conventions": prof.conventions or {},
            "is_default": prof.is_default,
            "created_at": prof.created_at.isoformat() if prof.created_at else None,
            "updated_at": prof.updated_at.isoformat() if prof.updated_at else None,
        }
