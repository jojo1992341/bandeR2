"""add content protection and purge

Revision ID: o7p8q9r0s1t2
Revises: n6o7p8q9r0s1
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "o7p8q9r0s1t2"
down_revision = "n6o7p8q9r0s1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("studios", sa.Column("security_settings", sa.JSON(), nullable=True))
    op.add_column(
        "exports",
        sa.Column("created_by", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "exports",
        sa.Column("creator_role", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "exports",
        sa.Column(
            "is_watermarked",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "exports",
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "exports",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exports", "expires_at")
    op.drop_column("exports", "is_archived")
    op.drop_column("exports", "is_watermarked")
    op.drop_column("exports", "creator_role")
    op.drop_column("exports", "created_by")
    op.drop_column("studios", "security_settings")
