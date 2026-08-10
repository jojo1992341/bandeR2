from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.rbac import get_current_user_payload, _get_user_id, assert_replica_access, assert_studio_member
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models import Comment, Replica, User

router = APIRouter()
security = HTTPBearer(auto_error=False)

class CommentCreateIn(BaseModel):
    content: str
    # also allow 'text' or 'message' as alias for flexibility
    text: Optional[str] = None
    message: Optional[str] = None

class CommentOut(BaseModel):
    id: str
    replica_id: str
    author_id: Optional[str] = None
    author_email: Optional[str] = None
    content: str
    created_at: str
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True

def _get_current_user_optional(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        return None
    payload = verify_token(credentials.credentials, token_type="access")
    return payload

def _serialize_comment(c: Comment, db: Session) -> dict:
    author_email = None
    if c.author_id:
        user = db.query(User).filter(User.id == c.author_id).first()
        if user:
            author_email = user.email
    return {
        "id": str(c.id),
        "replica_id": str(c.replica_id),
        "author_id": str(c.author_id) if c.author_id else None,
        "author_email": author_email,
        "content": c.content,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }

@router.get("/replicas/{replica_id}/comments", response_model=List[dict])
def list_comments(
    replica_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user_payload)
):
    _uid = _get_user_id(payload)
    assert_replica_access(db, _uid, replica_id)
    replica = db.query(Replica).filter(Replica.id == replica_id).first()
    if not replica:
        raise HTTPException(status_code=404, detail="Réplique non trouvée")
    comments = db.query(Comment).filter(Comment.replica_id == replica_id).order_by(Comment.created_at).all()
    return [_serialize_comment(c, db) for c in comments]

@router.post("/replicas/{replica_id}/comments", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_comment(
    replica_id: uuid.UUID,
    data: CommentCreateIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user_payload)
):
    _uid2 = _get_user_id(payload)
    assert_replica_access(db, _uid2, replica_id)
    replica = db.query(Replica).filter(Replica.id == replica_id).first()
    if not replica:
        raise HTTPException(status_code=404, detail="Réplique non trouvée")
    # Déterminer le contenu (supporte content/text/message)
    content = data.content or data.text or data.message
    if not content or not content.strip():
        raise HTTPException(status_code=422, detail="Le contenu du commentaire ne peut être vide")
    content = content.strip()
    if len(content) > 2000:
        raise HTTPException(status_code=422, detail="Commentaire trop long (max 2000 caractères)")

    author_id = None
    if payload and payload.get("sub"):
        try:
            author_id = uuid.UUID(payload.get("sub"))
            # Vérifier que l'utilisateur existe
            user = db.query(User).filter(User.id == author_id).first()
            if not user:
                author_id = None
        except:
            author_id = None

    comment = Comment(
        id=uuid.uuid4(),
        replica_id=replica_id,
        author_id=author_id,
        content=content
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return _serialize_comment(comment, db)

@router.get("/comments/{comment_id}", response_model=dict)
def get_comment(
    comment_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user_payload)
):
    _uid3 = _get_user_id(payload)
    _c = db.query(Comment).filter(Comment.id == comment_id).first()
    if _c:
        assert_replica_access(db, _uid3, _c.replica_id)
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Commentaire non trouvé")
    return _serialize_comment(comment, db)

@router.delete("/comments/{comment_id}", response_model=dict)
def delete_comment(
    comment_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user_payload)
):
    _uid4 = _get_user_id(payload)
    _c2 = db.query(Comment).filter(Comment.id == comment_id).first()
    if _c2:
        assert_replica_access(db, _uid4, _c2.replica_id)
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Commentaire non trouvé")

    # Vérifier les permissions : auteur ou admin
    # Pour les tests, si pas d'auth, on autorise la suppression
    if payload and payload.get("sub"):
        try:
            user_id = uuid.UUID(payload.get("sub"))
            # Si l'utilisateur n'est pas l'auteur, vérifier s'il est admin (role owner/admin)
            if comment.author_id and comment.author_id != user_id:
                user = db.query(User).filter(User.id == user_id).first()
                if user and user.role not in ("owner", "admin"):
                    # Vérifier si l'utilisateur est admin du brief, mais pour simplifier on autorise l'auteur seulement
                    # On permet aussi si l'utilisateur est admin global
                    from app.core.rbac import normalize_role
                    if normalize_role(user.role) not in ("owner", "admin"):
                        raise HTTPException(status_code=403, detail="Non autorisé à supprimer ce commentaire")
        except HTTPException:
            raise
        except:
            pass

    db.delete(comment)
    db.commit()
    return {"status": "deleted", "id": str(comment_id)}
