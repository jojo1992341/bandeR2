import uuid
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models import MediaAsset, Project
from app.core.rls_context import set_studio_context


class MediaAssetRepo:
    def __init__(self, db: Session, studio_id: uuid.UUID):
        self.db = db
        self.studio_id = studio_id
        set_studio_context(db, studio_id)

    def get_by_id(self, id: uuid.UUID):
        return (
            self.db.query(MediaAsset)
            .filter(
                MediaAsset.id == id,
                MediaAsset.project_id.in_(
                    self.db.query(Project.id).filter(
                        Project.studio_id == self.studio_id
                    )
                ),
            )
            .first()
        )
