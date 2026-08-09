"""transcript manual edits & history §10.2

Ajoute le suivi des corrections manuelles de transcription (G-014) :
- colonne `is_manually_edited` sur `transcript_segments` et `transcript_words` ;
- table `transcript_edit_history` (journal des modifications segment/mot).

Réversible (downgrade supprime la table et les colonnes).

Revision ID: 006_transcript_edits
Revises: 005_optimize_indexes_uuid7
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "006_transcript_edits"
down_revision = "005_optimize_indexes_uuid7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Suivi d'édition manuelle
    op.add_column(
        "transcript_segments",
        sa.Column(
            "is_manually_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "transcript_words",
        sa.Column(
            "is_manually_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Journal d'historique des corrections
    op.create_table(
        "transcript_edit_history",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column(
            "entity_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "studio_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field", sa.String(length=30), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column(
            "edited_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_transcript_edit_history_entity_id",
        "transcript_edit_history",
        ["entity_id"],
    )
    op.create_index(
        "ix_transcript_edit_history_entity_type",
        "transcript_edit_history",
        ["entity_type"],
    )
    op.create_index(
        "ix_transcript_edit_history_studio_id",
        "transcript_edit_history",
        ["studio_id"],
    )


def downgrade() -> None:
    op.drop_table("transcript_edit_history")
    op.drop_column("transcript_words", "is_manually_edited")
    op.drop_column("transcript_segments", "is_manually_edited")
