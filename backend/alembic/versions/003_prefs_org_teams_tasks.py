"""add preferences, organization, teams and tasks §16.1-§16.3

Modélise les préférences utilisateur, l'organisation des projets (dossiers/tags),
les équipes (sous-groupes Enterprise) et les tâches assignées (Vue « Mon activité »).

Tables créées:
- user_preferences  (§16.2 — thème, langue, raccourcis)
- project_folders   (§16.1 — dossiers d'organisation, imbriqués)
- project_tags_def  (§16.1 — tags studio-scopés)
- project_tags      (§16.1 — association M:N Project ↔ Tag)
- teams             (§16.3 — sous-groupes / équipes Enterprise)
- team_memberships  (§16.3 — appartenance utilisateur ↔ équipe)
- tasks             (§16.2 — tâches assignées, Vue « Mon activité »)

Toutes les entités studio-scopées portent `studio_id` (isolation tenant, §15.7).
Colonne ajoutée à projects : folder_id (FK vers project_folders).

Revision ID: 003_add_preferences_org_teams_tasks
Revises: 002_add_subscriptions_tables
Create Date: 2026-08-09
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "003_prefs_org_teams_tasks"
down_revision = "002_add_subscriptions_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # §16.2 — user_preferences (1:1 avec users)
    # ------------------------------------------------------------------
    op.create_table(
        "user_preferences",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("theme", sa.String(20), nullable=False, server_default=sa.text("'system'")),
        sa.Column("language", sa.String(10), nullable=False, server_default=sa.text("'fr'")),
        sa.Column(
            "custom_shortcuts",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_user_preferences_user", "user_preferences", ["user_id"]
    )

    # ------------------------------------------------------------------
    # §16.1 — project_folders (dossiers imbriqués studio-scopés)
    # ------------------------------------------------------------------
    op.create_table(
        "project_folders",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column(
            "studio_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "parent_folder_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_folders.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_folder_studio_name_parent",
        "project_folders",
        ["studio_id", "name", "parent_folder_id"],
    )

    # Colonne folder_id sur projects (ajoutée après création de project_folders)
    op.add_column(
        "projects",
        sa.Column(
            "folder_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_projects_folder_id", "projects", ["folder_id"])

    # ------------------------------------------------------------------
    # §16.1 — project_tags_def (tags studio-scopés)
    # ------------------------------------------------------------------
    op.create_table(
        "project_tags_def",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column(
            "studio_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("color", sa.String(20), nullable=False, server_default=sa.text("'#6366f1'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_tag_studio_name", "project_tags_def", ["studio_id", "name"]
    )

    # Association M:N Project ↔ ProjectTag
    op.create_table(
        "project_tags",
        sa.Column(
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_tags_def.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # ------------------------------------------------------------------
    # §16.3 — teams (sous-groupes / équipes Enterprise)
    # ------------------------------------------------------------------
    op.create_table(
        "teams",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column(
            "studio_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_unique_constraint("uq_team_studio_name", "teams", ["studio_id", "name"])

    op.create_table(
        "team_memberships",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column(
            "team_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("role", sa.String(50), nullable=False, server_default=sa.text("'member'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_team_user", "team_memberships", ["team_id", "user_id"]
    )

    # ------------------------------------------------------------------
    # §16.2 — tasks (Vue « Mon activité »)
    # ------------------------------------------------------------------
    op.create_table(
        "tasks",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column(
            "studio_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default=sa.text("'à_faire'"), index=True
        ),
        sa.Column(
            "assignee_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "created_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("team_memberships")
    op.drop_table("teams")
    op.drop_table("project_tags")
    op.drop_table("project_tags_def")
    op.drop_index("ix_projects_folder_id", table_name="projects")
    op.drop_column("projects", "folder_id")
    op.drop_table("project_folders")
    op.drop_table("user_preferences")
