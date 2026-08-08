"""add emotion tags §8.2.5

Revision ID: s0t1u2v3w4x5
Revises: r0s1t2u3v4w5
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "s0t1u2v3w4x5"
down_revision = "r0s1t2u3v4w5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "emotion_tags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("replica_id", sa.UUID(), nullable=False),
        sa.Column("media_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("tag_type", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.85"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="audio"),
        sa.Column("suggested_typo_codes", sa.JSON(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["replica_id"],
            ["replicas.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_id"],
            ["media_assets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_emotion_tags_replica_id"),
        "emotion_tags",
        ["replica_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_emotion_tags_media_id"),
        "emotion_tags",
        ["media_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_emotion_tags_project_id"),
        "emotion_tags",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_emotion_tags_tag_type"),
        "emotion_tags",
        ["tag_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_emotion_tags_label"),
        "emotion_tags",
        ["label"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_emotion_tags_label"), table_name="emotion_tags")
    op.drop_index(op.f("ix_emotion_tags_tag_type"), table_name="emotion_tags")
    op.drop_index(op.f("ix_emotion_tags_project_id"), table_name="emotion_tags")
    op.drop_index(op.f("ix_emotion_tags_media_id"), table_name="emotion_tags")
    op.drop_index(op.f("ix_emotion_tags_replica_id"), table_name="emotion_tags")
    op.drop_table("emotion_tags")
