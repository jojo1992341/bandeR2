"""add typographic profiles §2.4 §16.3 §10.2

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "t1u2v3w4x5y6"
down_revision = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "typographic_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("studio_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("codes", sa.JSON(), nullable=True),
        sa.Column("thresholds", sa.JSON(), nullable=True),
        sa.Column("conventions", sa.JSON(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["studio_id"], ["studios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_typographic_profiles_studio_id"), "typographic_profiles", ["studio_id"], unique=False)
    op.create_index(op.f("ix_typographic_profiles_name"), "typographic_profiles", ["name"], unique=False)
    op.create_unique_constraint("uq_studio_profile_name", "typographic_profiles", ["studio_id", "name"])

def downgrade() -> None:
    op.drop_constraint("uq_studio_profile_name", "typographic_profiles", type_="unique")
    op.drop_index(op.f("ix_typographic_profiles_name"), table_name="typographic_profiles")
    op.drop_index(op.f("ix_typographic_profiles_studio_id"), table_name="typographic_profiles")
    op.drop_table("typographic_profiles")
