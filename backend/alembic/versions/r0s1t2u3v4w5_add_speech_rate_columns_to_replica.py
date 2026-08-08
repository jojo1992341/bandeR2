"""add speech rate columns to replica

Revision ID: r0s1t2u3v4w5
Revises: q9r0s1t2u3v4
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "r0s1t2u3v4w5"
down_revision = "q9r0s1t2u3v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "replicas",
        sa.Column(
            "syllable_count",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "replicas",
        sa.Column(
            "speech_rate",
            sa.Numeric(precision=5, scale=2),
            nullable=True,
            server_default=sa.text("0.0"),
        ),
    )
    op.add_column(
        "replicas", sa.Column("speech_rate_alert", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("replicas", "speech_rate_alert")
    op.drop_column("replicas", "speech_rate")
    op.drop_column("replicas", "syllable_count")
