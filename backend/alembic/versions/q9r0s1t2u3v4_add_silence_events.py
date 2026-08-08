"""add silence events

Revision ID: q9r0s1t2u3v4
Revises: p8q9r0s1t2u3
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "q9r0s1t2u3v4"
down_revision = "p8q9r0s1t2u3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "silence_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("media_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["media_id"],
            ["media_assets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_silence_events_event_type"),
        "silence_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_silence_events_media_id"),
        "silence_events",
        ["media_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_silence_events_start_ms"),
        "silence_events",
        ["start_ms"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("silence_events")
