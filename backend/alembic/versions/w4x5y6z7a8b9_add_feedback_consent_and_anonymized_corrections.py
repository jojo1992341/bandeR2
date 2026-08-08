"""add feedback consent and anonymized corrections §8.5

Revision ID: w4x5y6z7a8b9
Revises: v3w4x5y6z7a8
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w4x5y6z7a8b9"
down_revision = "v3w4x5y6z7a8"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Ajouter feedback_settings à studios (JSON)
    op.add_column("studios", sa.Column("feedback_settings", sa.JSON(), nullable=True))

    # Créer table anonymized_corrections
    op.create_table(
        "anonymized_corrections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("studio_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("media_id", sa.UUID(), nullable=True),
        sa.Column("correction_type", sa.String(length=50), nullable=False),
        sa.Column("correction_data", sa.JSON(), nullable=True),
        sa.Column("original_hash", sa.String(length=64), nullable=True),
        sa.Column("corrected_hash", sa.String(length=64), nullable=True),
        sa.Column("heuristic_target", sa.String(length=50), nullable=True),
        sa.Column("model_version", sa.String(length=50), nullable=True),
        sa.Column("is_anonymized", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("consent_given", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("anonymized_studio_hash", sa.String(length=64), nullable=True),
        sa.Column("anonymized_user_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["studio_id"], ["studios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_anonymized_corrections_studio_id"), "anonymized_corrections", ["studio_id"], unique=False)
    op.create_index(op.f("ix_anonymized_corrections_project_id"), "anonymized_corrections", ["project_id"], unique=False)
    op.create_index(op.f("ix_anonymized_corrections_media_id"), "anonymized_corrections", ["media_id"], unique=False)
    op.create_index(op.f("ix_anonymized_corrections_correction_type"), "anonymized_corrections", ["correction_type"], unique=False)
    op.create_index(op.f("ix_anonymized_corrections_created_at"), "anonymized_corrections", ["created_at"], unique=False)

def downgrade() -> None:
    op.drop_index(op.f("ix_anonymized_corrections_created_at"), table_name="anonymized_corrections")
    op.drop_index(op.f("ix_anonymized_corrections_correction_type"), table_name="anonymized_corrections")
    op.drop_index(op.f("ix_anonymized_corrections_media_id"), table_name="anonymized_corrections")
    op.drop_index(op.f("ix_anonymized_corrections_project_id"), table_name="anonymized_corrections")
    op.drop_index(op.f("ix_anonymized_corrections_studio_id"), table_name="anonymized_corrections")
    op.drop_table("anonymized_corrections")
    op.drop_column("studios", "feedback_settings")
