import uuid
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.rls_context import set_studio_context
from app.models import Studio, Project, User, StudioMembership
from app.repositories.project_repo import ProjectRepo
from app.repositories.media_asset_repo import MediaAssetRepo
from app.core.password import hash_password


def test_isolation_project():
    db = SessionLocal()
    try:
        # Create studios
        studio_a = Studio(id=uuid.uuid4(), name="Studio A", plan="pro")
        studio_b = Studio(id=uuid.uuid4(), name="Studio B", plan="pro")
        db.add_all([studio_a, studio_b])
        db.commit()

        # Create user in Studio A
        user_a = User(
            id=uuid.uuid4(),
            email="user_a@test.com",
            hashed_password=hash_password("test"),
            role="adaptateur",
            is_active=True,
        )
        db.add(user_a)
        db.commit()
        db.refresh(user_a)

        membership_a = StudioMembership(
            id=uuid.uuid4(), studio_id=studio_a.id, user_id=user_a.id, role="adaptateur"
        )
        db.add(membership_a)

        # Project belonging to Studio B
        project_b = Project(
            id=uuid.uuid4(),
            studio_id=studio_b.id,
            title="Secret B",
            source_lang="fr",
            target_lang="fr",
            status="draft",
        )
        db.add(project_b)
        db.commit()
        db.refresh(project_b)
        db.refresh(studio_a)
        db.refresh(studio_b)

        # Repository with Studio A context tries to access Studio B project
        repo_a = ProjectRepo(db, studio_a.id)
        result = repo_a.get_by_id(project_b.id)

        # Anti-IDOR : même avec l'ID forcé, la ressource du studio B est invisible
        assert (
            result is None
        ), "Project from Studio B must be inaccessible to Studio A repo (filter + RLS)"

        # Note : RLS PostgreSQL est activée sur projects/media_assets (FORCE RLS).
        # Le filtrage applicatif (repo + session variable app.current_studio_id)
        # garantit l'isolation même si la connexion DB est superuser ;
        # en production, le rôle applicatif (non-superuser) bénéficiera pleinement de RLS.

    finally:
        # Cleanup
        db.query(StudioMembership).filter(
            StudioMembership.studio_id.in_([studio_a.id, studio_b.id])
        ).delete(synchronize_session=False)
        db.query(Project).filter(Project.id == project_b.id).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id == user_a.id).delete(synchronize_session=False)
        db.query(Studio).filter(Studio.id.in_([studio_a.id, studio_b.id])).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()
