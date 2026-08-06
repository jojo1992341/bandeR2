from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from app.core.security import (
    create_access_token, create_refresh_token, 
    verify_password, get_password_hash, require_role
)
from typing import Optional

router = APIRouter(prefix="/auth", tags=["auth"])

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class UserCreate(BaseModel):
    email: str
    password: str
    studio_id: int
    role: str = "guest"

@router.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Placeholder: in real impl, query DB
    if form_data.username == "admin@test.com" and form_data.password == "admin123":
        access = create_access_token({
            "sub": form_data.username, 
            "studio_id": 1, 
            "role": "admin"
        })
        refresh = create_refresh_token({"sub": form_data.username})
        return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Incorrect username or password")

@router.post("/register")
async def register(user: UserCreate):
    # Placeholder registration
    hashed = get_password_hash(user.password)
    return {"message": "User created", "email": user.email}

@router.get("/me")
async def me(current_user=Depends(require_role("guest"))):
    return {"user": current_user.sub, "studio_id": current_user.studio_id, "role": current_user.role}
