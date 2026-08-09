from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.core.database import get_db
from app.core.password import hash_password, verify_password
from app.core.auth_handler import (
    create_access_token,
    create_refresh_token,
    verify_token,
    verify_invite_token,
)
from app.core.rbac import get_current_user_payload, require_role
from app.core.pwned import check_pwned_password
from app.core.audit import (
    record_audit_log,
    check_login_anomalies,
    check_brute_force_anomalies,
    get_client_ip,
    get_client_country,
)
from app.models import User, StudioInvitation, StudioMembership, Studio

router = APIRouter()
security = HTTPBearer(auto_error=False)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    role: Optional[str] = "invité"


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = None
    code: Optional[str] = None

    def get_totp_code(self) -> Optional[str]:
        return self.totp_code or self.code


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: Optional[str] = None


class CheckPwnedIn(BaseModel):
    password: str


class MfaVerifyIn(BaseModel):
    code: Optional[str] = None
    totp_code: Optional[str] = None

    def get_code(self) -> Optional[str]:
        return self.code or self.totp_code


class RevokeSessionsIn(BaseModel):
    user_id: Optional[str] = None
    email: Optional[EmailStr] = None
    reason: Optional[str] = None


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if check_pwned_password(data.password):
        raise HTTPException(
            status_code=400,
            detail="Mot de passe compromis (détecté dans des fuites de données — HIBP)",
        )
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        role=data.role or "invité",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": str(user.id), "email": user.email, "role": user.role}


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    country = get_client_country(request)
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        record_audit_log(
            db,
            "login_failed",
            user_email=data.email,
            ip_address=ip,
            country_code=country,
            details={"reason": "invalid_credentials"},
        )
        check_brute_force_anomalies(db, data.email, ip, country)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # §16.2 — refus de connexion des comptes désactivés
    if not getattr(user, "is_active", True):
        record_audit_log(
            db,
            "login_failed",
            user_id=user.id,
            user_email=user.email,
            ip_address=ip,
            country_code=country,
            details={"reason": "account_deactivated"},
        )
        raise HTTPException(
            status_code=403, detail="Account deactivated"
        )

    mfa_required = (
        getattr(user, "totp_enabled", False)
        or user.role in ("owner", "admin")
        or any(m.role in ("owner", "admin") for m in user.memberships)
    )
    if getattr(user, "totp_enabled", False):
        totp_code = data.get_totp_code()
        if not totp_code:
            record_audit_log(
                db,
                "login_failed",
                user_id=user.id,
                user_email=user.email,
                ip_address=ip,
                country_code=country,
                details={"reason": "mfa_missing"},
            )
            raise HTTPException(
                status_code=401, detail="MFA required: TOTP code missing"
            )
        import pyotp

        secret = getattr(user, "totp_secret", None)
        if not secret or not pyotp.TOTP(secret).verify(
            totp_code, valid_window=1
        ):
            record_audit_log(
                db,
                "login_failed",
                user_id=user.id,
                user_email=user.email,
                ip_address=ip,
                country_code=country,
                details={"reason": "mfa_invalid"},
            )
            raise HTTPException(status_code=401, detail="Invalid TOTP code")

    check_login_anomalies(db, user.id, user.email, country, ip)
    record_audit_log(
        db,
        "login",
        user_id=user.id,
        user_email=user.email,
        ip_address=ip,
        country_code=country,
        details={
            "mfa_used": getattr(user, "totp_enabled", False),
            "role": user.role,
        },
    )

    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "tv": getattr(user, "token_version", 0) or 0,
    }
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "mfa_required": mfa_required,
        "mfa_enabled": getattr(user, "totp_enabled", False),
    }


@router.post("/refresh")
def refresh(data: RefreshIn, db: Session = Depends(get_db)):
    payload = verify_token(data.refresh_token, token_type="refresh")
    if not payload:
        raise HTTPException(
            status_code=401, detail="Invalid or expired refresh token"
        )

    sub = payload.get("sub")
    user = None
    if sub:
        try:
            user = db.query(User).filter(User.id == uuid.UUID(str(sub))).first()
            if user:
                token_tv = payload.get("tv", 0)
                user_tv = getattr(user, "token_version", 0) or 0
                if token_tv != user_tv:
                    raise HTTPException(
                        status_code=401,
                        detail="Token revoked (session revoked)",
                    )
        except HTTPException:
            raise
        except Exception:
            pass

    tv_val = (
        getattr(user, "token_version", 0) or 0 if user else payload.get("tv", 0)
    )
    new_access = create_access_token(
        {
            "sub": payload.get("sub"),
            "email": payload.get("email"),
            "role": payload.get("role"),
            "tv": tv_val,
        }
    )
    new_refresh = create_refresh_token(
        {
            "sub": payload.get("sub"),
            "email": payload.get("email"),
            "role": payload.get("role"),
            "tv": tv_val,
        }
    )
    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


@router.post("/logout")
def logout(data: LogoutIn = None):
    return {"message": "Logged out successfully"}


@router.post("/check-password-pwned")
def check_password_pwned_endpoint(data: CheckPwnedIn):
    is_pwned = check_pwned_password(data.password)
    return {
        "pwned": is_pwned,
        "message": (
            "Mot de passe compromis (HIBP)"
            if is_pwned
            else "Mot de passe sûr"
        ),
    }


@router.post("/mfa/setup")
@router.post("/mfa/enable")
@router.post("/mfa/generate")
def mfa_setup(
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    import pyotp

    user_id = uuid.UUID(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not getattr(user, "totp_secret", None):
        user.totp_secret = pyotp.random_base32()
        db.commit()
        db.refresh(user)

    totp = pyotp.TOTP(user.totp_secret)
    uri = totp.provisioning_uri(name=user.email, issuer_name="RythmoAI")
    return {
        "secret": user.totp_secret,
        "otpauth_url": uri,
        "message": "MFA setup initiated",
    }


@router.post("/mfa/verify")
@router.post("/mfa/activate")
@router.post("/mfa/confirm")
def mfa_verify(
    data: MfaVerifyIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    import pyotp

    code = data.get_code()
    if not code:
        raise HTTPException(status_code=400, detail="TOTP code required")

    user_id = uuid.UUID(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not getattr(user, "totp_secret", None):
        raise HTTPException(status_code=400, detail="MFA setup not initiated")

    if not pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    user.totp_enabled = True
    db.commit()
    db.refresh(user)
    return {
        "status": "success",
        "mfa_enabled": True,
        "message": "MFA activated successfully",
    }


@router.post("/mfa/disable")
def mfa_disable(
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = uuid.UUID(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.totp_enabled = False
    db.commit()
    return {
        "status": "success",
        "mfa_enabled": False,
        "message": "MFA disabled",
    }


@router.get("/mfa/status")
@router.get("/mfa")
def mfa_status(
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    user_id = uuid.UUID(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "mfa_enabled": getattr(user, "totp_enabled", False),
        "mfa_required": user.role in ("owner", "admin")
        or any(m.role in ("owner", "admin") for m in user.memberships),
    }


@router.post("/revoke-sessions")
@router.post("/revoke-all-sessions")
@router.post("/logout-all")
@router.post("/sessions/revoke")
def revoke_sessions(
    data: RevokeSessionsIn = None,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    caller_id = uuid.UUID(payload.get("sub"))
    caller_role = payload.get("role", "invité")

    target_user = None
    if data and (data.user_id or data.email):
        if caller_role not in ("owner", "admin"):
            raise HTTPException(
                status_code=403,
                detail="Only admins can revoke other users' sessions",
            )
        if data.user_id:
            try:
                target_user = (
                    db.query(User)
                    .filter(User.id == uuid.UUID(str(data.user_id)))
                    .first()
                )
            except Exception:
                target_user = None
        elif data.email:
            target_user = (
                db.query(User).filter(User.email == data.email).first()
            )

        if not target_user:
            raise HTTPException(status_code=404, detail="Target user not found")
    else:
        target_user = db.query(User).filter(User.id == caller_id).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    target_user.token_version = (getattr(target_user, "token_version", 0) or 0) + 1
    db.commit()
    db.refresh(target_user)

    return {
        "status": "success",
        "user_id": str(target_user.id),
        "token_version": target_user.token_version,
        "message": "All active sessions revoked successfully",
    }


class ActivateIn(BaseModel):
    token: Optional[str] = None
    invite_token: Optional[str] = None
    inviteToken: Optional[str] = None
    password: Optional[str] = None
    new_password: Optional[str] = None
    email: Optional[EmailStr] = None

    def get_token(self) -> Optional[str]:
        return self.token or self.invite_token or self.inviteToken

    def get_password(self) -> Optional[str]:
        return self.password or self.new_password


class ActivateOut(BaseModel):
    id: str
    email: EmailStr
    role: str
    studio_id: str
    message: str


def _activate_invite(token: str, password: str, email: Optional[str], db):
    if check_pwned_password(password):
        raise HTTPException(
            status_code=400,
            detail="Mot de passe compromis (détecté dans des fuites de données — HIBP)",
        )

    payload = verify_invite_token(token)
    if not payload:
        raise HTTPException(
            status_code=400, detail="Invalid or expired invite token"
        )

    token_email = payload.get("email")
    studio_id_str = payload.get("studio_id")
    role = payload.get("role") or "invité"
    if not token_email or not studio_id_str:
        raise HTTPException(
            status_code=400, detail="Invalid invite token payload"
        )

    if email and email.lower() != token_email.lower():
        raise HTTPException(
            status_code=400, detail="Email does not match invite token"
        )

    invitation = (
        db.query(StudioInvitation)
        .filter(StudioInvitation.token == token)
        .first()
    )
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.is_accepted:
        raise HTTPException(
            status_code=400, detail="Invitation already accepted"
        )
    now = datetime.now(timezone.utc)
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise HTTPException(status_code=400, detail="Invitation expired")

    if invitation.email.lower() != token_email.lower():
        raise HTTPException(
            status_code=400, detail="Invitation email mismatch"
        )

    studio_id = uuid.UUID(studio_id_str)
    studio = db.query(Studio).filter(Studio.id == studio_id).first()
    if not studio:
        raise HTTPException(status_code=404, detail="Studio not found")

    existing_user = db.query(User).filter(User.email == token_email).first()
    if existing_user:
        existing_membership = (
            db.query(StudioMembership)
            .filter(
                StudioMembership.studio_id == studio_id,
                StudioMembership.user_id == existing_user.id,
            )
            .first()
        )
        if existing_membership:
            raise HTTPException(
                status_code=400, detail="User already member of studio"
            )
        membership = StudioMembership(
            studio_id=studio_id, user_id=existing_user.id, role=role
        )
        db.add(membership)
        existing_user.role = role
        invitation.is_accepted = True
        invitation.accepted_at = now
        db.commit()
        db.refresh(existing_user)
        return existing_user, studio_id, role

    new_user = User(
        email=token_email,
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(new_user)
    db.flush()

    membership = StudioMembership(
        studio_id=studio_id, user_id=new_user.id, role=role
    )
    db.add(membership)

    invitation.is_accepted = True
    invitation.accepted_at = now
    db.commit()
    db.refresh(new_user)
    return new_user, studio_id, role


@router.post(
    "/activate",
    response_model=ActivateOut,
    status_code=status.HTTP_201_CREATED,
)
def activate(data: ActivateIn, db=Depends(get_db)):
    token = data.get_token()
    password = data.get_password()
    if not token or not password:
        raise HTTPException(
            status_code=422, detail="token and password are required"
        )
    user, studio_id, role = _activate_invite(token, password, data.email, db)
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "studio_id": str(studio_id),
        "message": "Account activated successfully",
    }


@router.post(
    "/invite/activate",
    response_model=ActivateOut,
    status_code=status.HTTP_201_CREATED,
)
def activate_alias(data: ActivateIn, db=Depends(get_db)):
    token = data.get_token()
    password = data.get_password()
    if not token or not password:
        raise HTTPException(
            status_code=422, detail="token and password are required"
        )
    user, studio_id, role = _activate_invite(token, password, data.email, db)
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "studio_id": str(studio_id),
        "message": "Account activated successfully",
    }


@router.get("/invite/verify")
def verify_invite(token: str, db=Depends(get_db)):
    payload = verify_invite_token(token)
    if not payload:
        raise HTTPException(
            status_code=400, detail="Invalid or expired invite token"
        )
    invitation = (
        db.query(StudioInvitation)
        .filter(StudioInvitation.token == token)
        .first()
    )
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.is_accepted:
        raise HTTPException(
            status_code=400, detail="Invitation already accepted"
        )
    now = datetime.now(timezone.utc)
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise HTTPException(status_code=400, detail="Invitation expired")
    return {
        "email": invitation.email,
        "role": invitation.role,
        "studio_id": str(invitation.studio_id),
        "expires_at": invitation.expires_at.isoformat(),
        "is_valid": True,
    }


@router.get("/me")
def me(payload: dict = Depends(get_current_user_payload)):
    return {
        "sub": payload.get("sub"),
        "email": payload.get("email"),
        "role": payload.get("role"),
    }


@router.get("/admin-only")
def admin_only(payload: dict = Depends(require_role("owner", "admin"))):
    return {"message": "Admin access granted", "user": payload.get("email")}
