from sqlalchemy import text
from sqlalchemy.orm import Session
import uuid


def set_studio_context(db: Session, studio_id: uuid.UUID):
    db.execute(text("SET app.current_studio_id = :sid"), {"sid": str(studio_id)})
