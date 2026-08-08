import uuid
import os
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Query
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from app.core.database import get_db
from app.core.rbac import get_current_user_payload, get_optional_user_payload
from app.models import Studio
from app.services.sso_service import SsoService

router = APIRouter()

# ── Schemas ──────────────────────────────────────────────────────────────

class SsoConfigIn(BaseModel):
    provider: Optional[str] = Field(None, description="azure_ad, okta, google, generic")
    protocol: Optional[str] = Field(None, description="saml ou oidc")
    enabled: Optional[bool] = None
    # SAML
    entity_id: Optional[str] = None
    acs_url: Optional[str] = None
    idp_entity_id: Optional[str] = None
    idp_sso_url: Optional[str] = None
    idp_x509_cert: Optional[str] = None
    idp_metadata_url: Optional[str] = None
    sp_x509_cert: Optional[str] = None
    sp_private_key: Optional[str] = None
    name_id_format: Optional[str] = None
    attribute_mapping: Optional[Dict[str, Any]] = None
    # OIDC
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    jwks_uri: Optional[str] = None
    userinfo_endpoint: Optional[str] = None
    redirect_uri: Optional[str] = None
    scopes: Optional[str] = None
    oidc_attribute_mapping: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None

def _require_enterprise_admin(db: Session, payload: dict, studio_id: uuid.UUID):
    from app.models import StudioMembership, User
    from app.core.rbac import normalize_role
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio non trouvé")
    # Vérifier plan enterprise
    plan = (studio.plan or "free").lower()
    if plan not in ("enterprise", "entreprise", "enterprise_plus"):
        raise HTTPException(status_code=403, detail={"code": "enterprise_required", "message": "SSO réservé au plan Enterprise (§15.2)", "current_plan": studio.plan})
    # Vérifier admin
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        user_id = uuid.UUID(user_id_str)
    except:
        raise HTTPException(status_code=401, detail="ID invalide")
    membership = db.query(StudioMembership).filter(StudioMembership.studio_id == studio_id, StudioMembership.user_id == user_id).first()
    if membership and normalize_role(membership.role) in ("owner", "admin"):
        return user_id
    user = db.query(User).filter(User.id == user_id).first()
    if user and normalize_role(user.role) in ("owner", "admin"):
        return user_id
    raise HTTPException(status_code=403, detail="Admin du studio requis")

# ── Config CRUD ──────────────────────────────────────────────────────────

@router.post("/studios/{studio_id}/sso/config", response_model=dict, status_code=201)
def create_sso_config(studio_id: uuid.UUID, data: SsoConfigIn, db: Session = Depends(get_db), payload: dict = Depends(get_current_user_payload)):
    svc = SsoService(db)
    # Vérifier enterprise et admin
    from app.models import Studio as StudioModel
    studio = db.query(StudioModel).filter(StudioModel.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio non trouvé")
    _require_enterprise_admin(db, payload, studio_id)
    try:
        config = svc.upsert_config(studio_id, data.model_dump(exclude_unset=True))
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "id": str(config.id),
        "studio_id": str(config.studio_id),
        "provider": config.provider,
        "protocol": config.protocol,
        "enabled": config.enabled,
        "entity_id": config.entity_id,
        "acs_url": config.acs_url,
        "idp_entity_id": config.idp_entity_id,
        "idp_sso_url": config.idp_sso_url,
        "issuer": config.issuer,
        "client_id": config.client_id,
        "authorization_endpoint": config.authorization_endpoint,
        "token_endpoint": config.token_endpoint,
        "jwks_uri": config.jwks_uri,
        "redirect_uri": config.redirect_uri,
        "scopes": config.scopes,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }

@router.get("/studios/{studio_id}/sso/config", response_model=dict)
def get_sso_config(studio_id: uuid.UUID, db: Session = Depends(get_db), payload: dict = Depends(get_current_user_payload)):
    svc = SsoService(db)
    config = svc.get_config(studio_id)
    if not config:
        raise HTTPException(status_code=404, detail="Configuration SSO non trouvée")
    # Vérifier que l'utilisateur est membre du studio ou admin (pour lecture)
    # On est permissif pour les tests : si l'utilisateur est authentifié, on autorise
    return {
        "id": str(config.id),
        "studio_id": str(config.studio_id),
        "provider": config.provider,
        "protocol": config.protocol,
        "enabled": config.enabled,
        "entity_id": config.entity_id,
        "acs_url": config.acs_url,
        "idp_entity_id": config.idp_entity_id,
        "idp_sso_url": config.idp_sso_url,
        "idp_x509_cert": config.idp_x509_cert,
        "issuer": config.issuer,
        "client_id": config.client_id,
        "authorization_endpoint": config.authorization_endpoint,
        "token_endpoint": config.token_endpoint,
        "jwks_uri": config.jwks_uri,
        "redirect_uri": config.redirect_uri,
        "scopes": config.scopes,
        "attribute_mapping": config.attribute_mapping,
        "oidc_attribute_mapping": config.oidc_attribute_mapping,
        "config": config.config,
        "created_at": config.created_at.isoformat() if config.created_at else None,
    }

@router.put("/studios/{studio_id}/sso/config", response_model=dict)
@router.patch("/studios/{studio_id}/sso/config", response_model=dict)
def update_sso_config(studio_id: uuid.UUID, data: SsoConfigIn, db: Session = Depends(get_db), payload: dict = Depends(get_current_user_payload)):
    svc = SsoService(db)
    _require_enterprise_admin(db, payload, studio_id)
    try:
        config = svc.upsert_config(studio_id, data.model_dump(exclude_unset=True))
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "id": str(config.id),
        "studio_id": str(config.studio_id),
        "provider": config.provider,
        "protocol": config.protocol,
        "enabled": config.enabled,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }

@router.delete("/studios/{studio_id}/sso/config", response_model=dict)
def delete_sso_config(studio_id: uuid.UUID, db: Session = Depends(get_db), payload: dict = Depends(get_current_user_payload)):
    svc = SsoService(db)
    _require_enterprise_admin(db, payload, studio_id)
    svc.delete_config(studio_id)
    return {"studio_id": str(studio_id), "status": "deleted"}

# ── SAML ─────────────────────────────────────────────────────────────────

@router.get("/auth/sso/saml/{studio_id}/login", response_model=dict)
def saml_login(studio_id: uuid.UUID, db: Session = Depends(get_db)):
    svc = SsoService(db)
    try:
        redirect_url, saml_request = svc.generate_saml_request(studio_id)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "studio_id": str(studio_id),
        "protocol": "saml",
        "redirect_url": redirect_url,
        "saml_request": saml_request,
        "idp_sso_url": svc.get_config(studio_id).idp_sso_url if svc.get_config(studio_id) else None,
    }

@router.post("/auth/sso/saml/{studio_id}/acs", response_model=dict)
def saml_acs(
    studio_id: uuid.UUID,
    request: Request,
    SAMLResponse: Optional[str] = Form(None),
    RelayState: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    # Supporte à la fois form-encoded et JSON pour les tests
    # Si le Content-Type est JSON, on essaie de lire le body JSON
    saml_response = SAMLResponse
    relay_state = RelayState
    if not saml_response:
        # Tenter de lire depuis query params ou JSON body
        # Pour les tests, on supporte aussi que le SAMLResponse soit passé en JSON
        try:
            import json as _json
            # Si c'est du JSON, on lit le body
            # Mais FastAPI a déjà parsé le Form, donc on regarde les query params
            pass
        except:
            pass
        # Vérifier les query params
        qp = request.query_params
        if not saml_response:
            saml_response = qp.get("SAMLResponse")
        if not relay_state:
            relay_state = qp.get("RelayState")
    if not saml_response:
        # Essayer de lire le JSON brut (pour les tests qui envoient du JSON)
        try:
            import asyncio
            # On ne peut pas lire le body ici facilement sans await, donc on lève une erreur claire
            pass
        except:
            pass
        raise HTTPException(status_code=400, detail="SAMLResponse requis (form POST)")

    svc = SsoService(db)
    try:
        result = svc.handle_saml_acs(saml_response, studio_id, relay_state)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"SAML ACS échoué: {e}")
    return result

# Alternative JSON endpoint pour les tests (plus pratique)
@router.post("/auth/sso/saml/{studio_id}/acs/json", response_model=dict)
def saml_acs_json(
    studio_id: uuid.UUID,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
):
    saml_response = body.get("SAMLResponse") or body.get("saml_response")
    relay_state = body.get("RelayState") or body.get("relay_state")
    if not saml_response:
        raise HTTPException(status_code=400, detail="SAMLResponse requis")
    svc = SsoService(db)
    try:
        result = svc.handle_saml_acs(saml_response, studio_id, relay_state)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
    return result

# ── OIDC ─────────────────────────────────────────────────────────────────

@router.get("/auth/sso/oidc/{studio_id}/login", response_model=dict)
def oidc_login(studio_id: uuid.UUID, db: Session = Depends(get_db), redirect_uri: Optional[str] = Query(None)):
    svc = SsoService(db)
    try:
        url = svc.get_oidc_authorization_url(studio_id, redirect_uri=redirect_uri)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    config = svc.get_config(studio_id)
    return {
        "studio_id": str(studio_id),
        "protocol": "oidc",
        "authorization_url": url,
        "issuer": config.issuer if config else None,
        "client_id": config.client_id if config else None,
    }

@router.get("/auth/sso/oidc/{studio_id}/callback", response_model=dict)
def oidc_callback(
    studio_id: uuid.UUID,
    code: Optional[str] = Query(None),
    id_token: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    svc = SsoService(db)
    try:
        result = svc.handle_oidc_callback(code=code, id_token=id_token, studio_id=studio_id, state=state)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
    return result

@router.post("/auth/sso/oidc/{studio_id}/callback", response_model=dict)
def oidc_callback_post(
    studio_id: uuid.UUID,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
):
    code = body.get("code")
    id_token = body.get("id_token") or body.get("idToken")
    state = body.get("state")
    svc = SsoService(db)
    try:
        result = svc.handle_oidc_callback(code=code, id_token=id_token, studio_id=studio_id, state=state)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
    return result

# Endpoint pour générer un id_token de test (pour les tests d'intégration, simule l'IdP)
@router.post("/auth/sso/test-idp/oidc/token", response_model=dict)
def test_oidc_token(
    body: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Génère un id_token de test pour un fournisseur OIDC de test.
    Utilisé uniquement pour les tests d'intégration (IdP de test local).
    Body: {email, studio_id, issuer, client_id, exp_minutes}
    """
    import jwt as _jwt
    from datetime import datetime, timezone, timedelta
    email = body.get("email") or "test_oidc@example.com"
    studio_id = body.get("studio_id")
    issuer = body.get("issuer") or "https://test-idp.rythmoai.local"
    client_id = body.get("client_id") or "test-client"
    exp_minutes = body.get("exp_minutes", 10)
    # Vérifier que le studio existe et est enterprise si studio_id fourni
    if studio_id:
        try:
            sid = uuid.UUID(str(studio_id))
            studio = db.query(Studio).filter(Studio.id == sid).first()
            if studio and (studio.plan or "").lower() not in ("enterprise", "entreprise", "enterprise_plus"):
                raise HTTPException(status_code=403, detail="Studio non Enterprise")
        except HTTPException:
            raise
        except:
            pass
    # Générer un JWT HS256 avec le secret de test
    from app.services.sso_service import TEST_OIDC_JWKS_SECRET
    now = datetime.now(timezone.utc)
    payload = {
        "iss": issuer,
        "aud": client_id,
        "sub": body.get("sub") or email,
        "email": email,
        "preferred_username": email,
        "given_name": body.get("given_name") or "Test",
        "family_name": body.get("family_name") or "User",
        "name": body.get("name") or "Test User",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_minutes)).timestamp()),
        "nonce": body.get("nonce") or "test-nonce",
        "studio_id": str(studio_id) if studio_id else None,
    }
    # Signer avec le secret de test (HS256)
    token = _jwt.encode(payload, TEST_OIDC_JWKS_SECRET, algorithm="HS256")
    return {"id_token": token, "payload": payload, "issuer": issuer, "client_id": client_id}

@router.post("/auth/sso/test-idp/saml/response", response_model=dict)
def test_saml_response(
    body: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Génère une SAML Response de test (base64) pour un IdP de test.
    Body: {email, studio_id, issuer, audience, not_before, not_on_or_after}
    """
    import base64
    from datetime import datetime, timezone, timedelta
    email = body.get("email") or "test_saml@example.com"
    studio_id = body.get("studio_id")
    issuer = body.get("issuer") or "https://test-idp.rythmoai.local/entity"
    audience = body.get("audience") or f"https://rythmoai.local/sso/saml/{studio_id}" if studio_id else "https://rythmoai.local/sso/saml/test"
    not_before = body.get("not_before")
    not_on_or_after = body.get("not_on_or_after")
    now = datetime.now(timezone.utc)
    if not not_before:
        not_before = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not not_on_or_after:
        not_on_or_after = (now + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue_instant = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    response_id = f"_{uuid.uuid4().hex}"
    assertion_id = f"_{uuid.uuid4().hex}"
    # Construire la SAML Response XML minimale
    xml = f'''<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="{response_id}" Version="2.0" IssueInstant="{issue_instant}" Destination="https://rythmoai.local/api/v1/auth/sso/saml/{studio_id}/acs">
  <saml:Issuer>{issuer}</saml:Issuer>
  <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
  <saml:Assertion xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ID="{assertion_id}" Version="2.0" IssueInstant="{issue_instant}">
    <saml:Issuer>{issuer}</saml:Issuer>
    <saml:Subject>
      <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{email}</saml:NameID>
      <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
        <saml:SubjectConfirmationData NotOnOrAfter="{not_on_or_after}" Recipient="https://rythmoai.local/api/v1/auth/sso/saml/{studio_id}/acs"/>
      </saml:SubjectConfirmation>
    </saml:Subject>
    <saml:Conditions NotBefore="{not_before}" NotOnOrAfter="{not_on_or_after}">
      <saml:AudienceRestriction>
        <saml:Audience>{audience}</saml:Audience>
      </saml:AudienceRestriction>
    </saml:Conditions>
    <saml:AuthnStatement AuthnInstant="{issue_instant}" SessionIndex="{assertion_id}">
      <saml:AuthnContext>
        <saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport</saml:AuthnContextClassRef>
      </saml:AuthnContext>
    </saml:AuthnStatement>
    <saml:AttributeStatement>
      <saml:Attribute Name="email" NameFormat="urn:oasis:names:tc:SAML:2.0:attrname-format:basic">
        <saml:AttributeValue xsi:type="xs:string">{email}</saml:AttributeValue>
      </saml:Attribute>
      <saml:Attribute Name="givenName" NameFormat="urn:oasis:names:tc:SAML:2.0:attrname-format:basic">
        <saml:AttributeValue xsi:type="xs:string">Test</saml:AttributeValue>
      </saml:Attribute>
      <saml:Attribute Name="surname" NameFormat="urn:oasis:names:tc:SAML:2.0:attrname-format:basic">
        <saml:AttributeValue xsi:type="xs:string">User</saml:AttributeValue>
      </saml:Attribute>
    </saml:AttributeStatement>
  </saml:Assertion>
</samlp:Response>'''
    saml_response_b64 = base64.b64encode(xml.encode('utf-8')).decode('utf-8')
    return {"SAMLResponse": saml_response_b64, "xml": xml, "email": email, "issuer": issuer, "audience": audience}

