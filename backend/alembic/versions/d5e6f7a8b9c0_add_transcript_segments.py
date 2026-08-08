"""add_transcript_segments

Revision ID: d5e6f7a8b9c0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-07 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('transcript_segments',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('media_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('media_assets.id'), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('start_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('end_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('language', sa.String(length=10), server_default='fr'),
        sa.Column('confidence_score', sa.Numeric(4, 3), server_default='0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_transcript_segments_media_id', 'transcript_segments', ['media_id'])

def downgrade():
    op.drop_index('ix_transcript_segments_media_id', table_name='transcript_segments')
    op.drop_table('transcript_segments')
