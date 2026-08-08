from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.password import hash_password, verify_password
from app.core.auth_handler import (
    create_access_token,
    create_refresh_token,
    verify_token,
)
from app.core.rbac import get_current_user_payload, require_role
from app.models import User

router = APIRouter()
security = HTTPBearer(auto_error=False)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    role: Optional[str] = "invité"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: Optional[str] = None


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(data: RegisterIn, db: Session = Depends(get_db)):
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
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    payload = {"sub": str(user.id), "email": user.email, "role": user.role}
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh")
def refresh(data: RefreshIn):
    payload = verify_token(data.refresh_token, token_type="refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    new_access = create_access_token(
        {
            "sub": payload.get("sub"),
            "email": payload.get("email"),
            "role": payload.get("role"),
        }
    )
    new_refresh = create_refresh_token(
        {
            "sub": payload.get("sub"),
            "email": payload.get("email"),
            "role": payload.get("role"),
        }
    )
    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


@router.post("/logout")
def logout(data: LogoutIn = None):
    # Rotation / revocation minimal : token roté à chaque utilisation ;
    # pour la déconnexion, on renvoie simplement un OK.
    return {"message": "Logged out successfully"}


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
