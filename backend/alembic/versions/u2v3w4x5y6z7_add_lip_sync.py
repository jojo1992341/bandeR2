"""add lip sync frames and results §8.2.6 §11.4

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "u2v3w4x5y6z7"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "lip_sync_frames",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("media_id", sa.UUID(), nullable=False),
        sa.Column("timestamp_ms", sa.Integer(), nullable=False),
        sa.Column("opening", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("face_visible", sa.Boolean(), nullable=False),
        sa.Column("is_close_up", sa.Boolean(), nullable=False),
        sa.Column("raw_distance", sa.Float(), nullable=True),
        sa.Column("face_bbox", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["media_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lip_sync_frames_media_id"), "lip_sync_frames", ["media_id"], unique=False)
    op.create_index(op.f("ix_lip_sync_frames_timestamp_ms"), "lip_sync_frames", ["timestamp_ms"], unique=False)
    op.create_table(
        "lip_sync_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("media_id", sa.UUID(), nullable=False),
        sa.Column("fps", sa.Integer(), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("face_visible_ratio", sa.Float(), nullable=False),
        sa.Column("close_up_ratio", sa.Float(), nullable=False),
        sa.Column("curve", sa.JSON(), nullable=True),
        sa.Column("detector_version", sa.String(length=50), nullable=True),
        sa.Column("feature_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["media_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lip_sync_results_media_id"), "lip_sync_results", ["media_id"], unique=True)

def downgrade() -> None:
    op.drop_index(op.f("ix_lip_sync_results_media_id"), table_name="lip_sync_results")
    op.drop_table("lip_sync_results")
    op.drop_index(op.f("ix_lip_sync_frames_timestamp_ms"), table_name="lip_sync_frames")
    op.drop_index(op.f("ix_lip_sync_frames_media_id"), table_name="lip_sync_frames")
    op.drop_table("lip_sync_frames")
