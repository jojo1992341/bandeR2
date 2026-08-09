"""
Chargeur de fixtures versionnées (§9.7 CDC).

Le jeu de données couvre les entités principales et les ajouts récents
(préférences §16.2, organisation de projets §16.1, équipes §16.3, tâches §16.2)
afin de valider qu'un schéma migré jusqu'à `head` est pleinement utilisable.

Toutes les fonctions attendent une `Session` SQLAlchemy ouverte. Les PK utilisent
le défaut applicatif UUID v7 (§9.5). Le chargement est idempotent via
`clear_fixtures` avant insertion.
"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import (
    MediaAsset,
    Project,
    ProjectFolder,
    ProjectTag,
    Replica,
    RythmoBand,
    Studio,
    StudioMembership,
    Task,
    Team,
    TeamMembership,
    User,
    UserPreferences,
)

RECETTE_PASSWORD = "Recette123!"


def clear_fixtures(session: Session) -> None:
    """Purge les données créées par les fixtures (ordre anti-FK)."""
    models = (
        Task,
        TeamMembership,
        Team,
        Replica,
        RythmoBand,
        MediaAsset,
        Project,
        ProjectTag,
        ProjectFolder,
        UserPreferences,
        StudioMembership,
        User,
        Studio,
    )
    for model in models:
        session.query(model).delete(synchronize_session=False)
    session.commit()


def load_fixtures(session: Session) -> dict:
    """
    Charge le jeu de données de référence et retourne un dictionnaire des IDs
    créés (pour assertions d'intégrité).

    Idempotent : purge d'abord les éventuelles données fixtures précédentes.
    """
    clear_fixtures(session)

    # --------------------------------------------------------------
    # Studios
    # --------------------------------------------------------------
    studio_recette = Studio(name="Studio Recette", plan="enterprise")
    studio_demo = Studio(name="Studio Démo", plan="pro")
    session.add_all([studio_recette, studio_demo])
    session.flush()

    # --------------------------------------------------------------
    # Utilisateurs + appartenances
    # --------------------------------------------------------------
    pw = hash_password(RECETTE_PASSWORD)
    admin = User(
        email="admin@recette.local",
        hashed_password=pw,
        role="owner",
        is_active=True,
    )
    adaptor = User(
        email="adaptateur@recette.local",
        hashed_password=pw,
        role="adaptateur",
        is_active=True,
    )
    calligraphe = User(
        email="calligraphe@recette.local",
        hashed_password=pw,
        role="calligraphe",
        is_active=True,
    )
    session.add_all([admin, adaptor, calligraphe])
    session.flush()

    memberships = [
        StudioMembership(
            studio_id=studio_recette.id, user_id=admin.id, role="owner"
        ),
        StudioMembership(
            studio_id=studio_recette.id, user_id=adaptor.id, role="adaptateur"
        ),
        StudioMembership(
            studio_id=studio_recette.id,
            user_id=calligraphe.id,
            role="calligraphe",
        ),
    ]
    session.add_all(memberships)

    # --------------------------------------------------------------
    # Préférences (§16.2)
    # --------------------------------------------------------------
    session.add(
        UserPreferences(
            user_id=admin.id,
            theme="dark",
            language="fr",
            custom_shortcuts={"save": "Ctrl+S"},
        )
    )

    # --------------------------------------------------------------
    # Organisation de projets (§16.1)
    # --------------------------------------------------------------
    folder_jeunesse = ProjectFolder(
        studio_id=studio_recette.id, name="Pôle jeunesse"
    )
    tag_saison = ProjectTag(
        studio_id=studio_recette.id, name="saison-1", color="#6366f1"
    )
    session.add_all([folder_jeunesse, tag_saison])
    session.flush()

    # --------------------------------------------------------------
    # Projets + média + bande rythmo + répliques
    # --------------------------------------------------------------
    project = Project(
        studio_id=studio_recette.id,
        title="Film exemple",
        status="Pret_pour_edition",
        folder_id=folder_jeunesse.id,
    )
    project.tags = [tag_saison]
    session.add(project)
    session.flush()

    media = MediaAsset(
        project_id=project.id,
        storage_path="recette/film_exemple.mp4",
        status="confirmed",
    )
    session.add(media)
    session.flush()

    band = RythmoBand(
        project_id=project.id,
        version_number=1,
        status="draft",
        is_master=True,
    )
    session.add(band)
    session.flush()

    replicas = [
        Replica(
            media_id=media.id,
            rythmo_band_id=band.id,
            text="Bonjour le monde",
            start_ms=0,
            end_ms=2000,
            order_index=0,
            typo_codes={"italique": True},
        ),
        Replica(
            media_id=media.id,
            rythmo_band_id=band.id,
            text="Au revoir",
            start_ms=2000,
            end_ms=3500,
            order_index=1,
        ),
    ]
    session.add_all(replicas)

    # --------------------------------------------------------------
    # Équipe (§16.3, Enterprise) + membre
    # --------------------------------------------------------------
    team = Team(
        studio_id=studio_recette.id,
        name="Pôle films",
        description="Équipe films du studio recette",
    )
    session.add(team)
    session.flush()
    session.add(
        TeamMembership(team_id=team.id, user_id=adaptor.id, role="member")
    )

    # --------------------------------------------------------------
    # Tâche assignée (§16.2, Vue « Mon activité »)
    # --------------------------------------------------------------
    session.add(
        Task(
            studio_id=studio_recette.id,
            project_id=project.id,
            title="Relire les répliques",
            status="en_cours",
            assignee_id=adaptor.id,
            created_by=admin.id,
        )
    )

    session.commit()

    return {
        "studios": [studio_recette.id, studio_demo.id],
        "users": [admin.id, adaptor.id, calligraphe.id],
        "project": project.id,
        "media": media.id,
        "band": band.id,
        "folder": folder_jeunesse.id,
        "tag": tag_saison.id,
        "team": team.id,
    }


def fixtures_summary(session: Session) -> dict:
    """Retourne un résumé des comptes par table (pour assertions d'intégrité)."""
    insp_models = {
        "studios": Studio,
        "users": User,
        "studio_memberships": StudioMembership,
        "user_preferences": UserPreferences,
        "project_folders": ProjectFolder,
        "project_tags": ProjectTag,
        "projects": Project,
        "media_assets": MediaAsset,
        "rythmo_bands": RythmoBand,
        "replicas": Replica,
        "teams": Team,
        "team_memberships": TeamMembership,
        "tasks": Task,
    }
    summary = {}
    for name, model in insp_models.items():
        summary[name] = session.query(model).count()
    return summary
