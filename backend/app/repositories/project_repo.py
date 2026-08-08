import uuid
from sqlalchemy.orm import Session
from app.models import Project
from app.core.rls_context import set_studio_context


class ProjectRepo:
    def __init__(self, db: Session, studio_id: uuid.UUID):
        self.db = db
        self.studio_id = studio_id
        set_studio_context(db, studio_id)

    def get_by_id(self, id: uuid.UUID):
        return (
            self.db.query(Project)
            .filter(Project.id == id, Project.studio_id == self.studio_id)
            .first()
        )

    def list_by_studio(self, limit: int = 20, offset: int = 0):
        return (
            self.db.query(Project)
            .filter(Project.studio_id == self.studio_id)
            .order_by(Project.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
