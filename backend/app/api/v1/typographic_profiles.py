import uuid
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.rbac import get_current_user_payload, get_optional_user_payload
from app.core.audit import record_audit_log
from app.models import Studio, TypographicProfile
from app.services.typographic_profile_service import TypographicProfileService, DEFAULT_CODES, DEFAULT_THRESHOLDS, validate_profile_payload

router = APIRouter()

class TypographicProfileIn(BaseModel):
    name: str
    description: Optional[str] = None
    codes: Optional[Dict[str, Any]] = None
    thresholds: Optional[Dict[str, Any]] = None
    conventions: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None

class TypographicProfilePatchIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    codes: Optional[Dict[str, Any]] = None
    thresholds: Optional[Dict[str, Any]] = None
    conventions: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None

class BulkPatchIn(BaseModel):
    profiles: Optional[List[Dict[str, Any]]] = None
    # also allow direct fields for single profile bulk creation via PATCH
    name: Optional[str] = None
    description: Optional[str] = None
    codes: Optional[Dict[str, Any]] = None
    thresholds: Optional[Dict[str, Any]] = None
    conventions: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None

def _require_admin_or_owner(db: Session, payload: Optional[dict], studio_id: uuid.UUID):
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user_id = uuid.UUID(user_id_str)
    except:
        raise HTTPException(status_code=401, detail="Invalid user id")
    # check studio membership
    from app.models import StudioMembership, User
    from app.core.rbac import normalize_role
    membership = db.query(StudioMembership).filter(StudioMembership.studio_id == studio_id, StudioMembership.user_id == user_id).first()
    if membership and normalize_role(membership.role) in ("owner", "admin"):
        return user_id
    user = db.query(User).filter(User.id == user_id).first()
    if user and normalize_role(user.role) in ("owner", "admin"):
        return user_id
    raise HTTPException(status_code=403, detail="Insufficient permissions: studio admin required")

@router.get("/studios/{studio_id}/typographic-profiles", response_model=Dict[str, Any])
@router.get("/api/v1/studios/{studio_id}/typographic-profiles", response_model=Dict[str, Any])
def get_typographic_profiles(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_optional_user_payload),
):
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio non trouvé")
    svc = TypographicProfileService(db)
    profiles = svc.list_by_studio(studio_id)
    return {
        "studio_id": str(studio_id),
        "count": len(profiles),
        "profiles": [svc.serialize(p) for p in profiles],
        "default_profile": svc.serialize(svc.get_default(studio_id)) if svc.get_default(studio_id) else None,
    }

@router.post("/studios/{studio_id}/typographic-profiles", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
@router.post("/api/v1/studios/{studio_id}/typographic-profiles", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_typographic_profile(
    studio_id: uuid.UUID,
    data: TypographicProfileIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user_payload),
):
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio non trouvé")
    _require_admin_or_owner(db, payload, studio_id)
    svc = TypographicProfileService(db)
    try:
        prof = svc.create(studio_id, data.model_dump(exclude_unset=False))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    # audit
    try:
        record_audit_log(db, "typographic_profile_create", user_id=uuid.UUID(payload.get("sub")), user_email=payload.get("email"), studio_id=studio_id, details={"profile_id": str(prof.id), "name": prof.name})
    except Exception:
        pass
    return svc.serialize(prof)

@router.patch("/studios/{studio_id}/typographic-profiles", response_model=Dict[str, Any])
@router.patch("/api/v1/studios/{studio_id}/typographic-profiles", response_model=Dict[str, Any])
def patch_typographic_profiles(
    studio_id: uuid.UUID,
    data: Dict[str, Any],
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user_payload),
):
    """
    PATCH collection §10.2
    - Si body contient {"profiles": [...]}, bulk upsert
    - Si body contient un seul profil {name, codes, thresholds...}, create ou update ce profil
    - Si body contient {"codes": {...}, "thresholds": {...}} sans name, met à jour le profil par défaut (ou en crée un)
    Permet à un admin studio de configurer ses codes et seuils, avec plusieurs profils possibles.
    """
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio non trouvé")
    _require_admin_or_owner(db, payload, studio_id)
    svc = TypographicProfileService(db)

    # Cas 1: bulk profiles list
    if "profiles" in data and isinstance(data["profiles"], list):
        profiles_payload = data["profiles"]
        result_profiles = svc.bulk_upsert(studio_id, profiles_payload)
        return {
            "studio_id": str(studio_id),
            "count": len(result_profiles),
            "profiles": [svc.serialize(p) for p in result_profiles],
            "status": "bulk_updated",
        }

    # Cas 2: single profile with name -> upsert that profile
    if "name" in data and data["name"]:
        name = str(data["name"]).strip()
        existing = db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio_id, TypographicProfile.name == name).first()
        if existing:
            try:
                updated = svc.update(studio_id, existing.id, data)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {
                "studio_id": str(studio_id),
                "profile": svc.serialize(updated),
                "status": "updated",
            }
        else:
            # create
            try:
                prof = svc.create(studio_id, data)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {
                "studio_id": str(studio_id),
                "profile": svc.serialize(prof),
                "status": "created",
            }

    # Cas 3: patch du profil par défaut (codes/thresholds sans name)
    # On met à jour le profil par défaut, ou on en crée un si aucun
    codes = data.get("codes")
    thresholds = data.get("thresholds")
    conventions = data.get("conventions")
    is_default = data.get("is_default")

    # Récupérer profil par défaut ou créer un "Default"
    default_prof = svc.get_default(studio_id)
    if not default_prof:
        # Créer un profil Default avec les valeurs fournies + défauts
        payload_create = {
            "name": "Default",
            "codes": codes or DEFAULT_CODES,
            "thresholds": thresholds or DEFAULT_THRESHOLDS,
            "conventions": conventions or {},
            "is_default": True,
        }
        try:
            prof = svc.create(studio_id, payload_create)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {
            "studio_id": str(studio_id),
            "profile": svc.serialize(prof),
            "status": "created_default",
        }
    else:
        # Patch le défaut
        patch_data = {}
        if codes is not None:
            patch_data["codes"] = codes
        if thresholds is not None:
            patch_data["thresholds"] = thresholds
        if conventions is not None:
            patch_data["conventions"] = conventions
        if is_default is not None:
            patch_data["is_default"] = is_default
        if not patch_data:
            raise HTTPException(status_code=422, detail="Aucune donnée à mettre à jour (codes, thresholds, conventions)")
        try:
            updated = svc.update(studio_id, default_prof.id, patch_data)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {
            "studio_id": str(studio_id),
            "profile": svc.serialize(updated),
            "status": "updated_default",
        }

@router.get("/studios/{studio_id}/typographic-profiles/{profile_id}", response_model=Dict[str, Any])
@router.get("/api/v1/studios/{studio_id}/typographic-profiles/{profile_id}", response_model=Dict[str, Any])
def get_typographic_profile(
    studio_id: uuid.UUID,
    profile_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_optional_user_payload),
):
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio non trouvé")
    svc = TypographicProfileService(db)
    prof = svc.get_by_id(studio_id, profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profil non trouvé")
    return svc.serialize(prof)

@router.patch("/studios/{studio_id}/typographic-profiles/{profile_id}", response_model=Dict[str, Any])
@router.patch("/api/v1/studios/{studio_id}/typographic-profiles/{profile_id}", response_model=Dict[str, Any])
def patch_typographic_profile(
    studio_id: uuid.UUID,
    profile_id: uuid.UUID,
    data: TypographicProfilePatchIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user_payload),
):
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio non trouvé")
    _require_admin_or_owner(db, payload, studio_id)
    svc = TypographicProfileService(db)
    try:
        updated = svc.update(studio_id, profile_id, data.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return svc.serialize(updated)

@router.delete("/studios/{studio_id}/typographic-profiles/{profile_id}", response_model=Dict[str, Any])
@router.delete("/api/v1/studios/{studio_id}/typographic-profiles/{profile_id}", response_model=Dict[str, Any])
def delete_typographic_profile(
    studio_id: uuid.UUID,
    profile_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user_payload),
):
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio non trouvé")
    _require_admin_or_owner(db, payload, studio_id)
    svc = TypographicProfileService(db)
    try:
        svc.delete(studio_id, profile_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"studio_id": str(studio_id), "profile_id": str(profile_id), "status": "deleted"}

# Legacy endpoint for backward compat: PATCH /studios/{id} with custom_typographic_profiles
# Déjà géré via studio model JSON, mais on expose aussi via le service pour migration
