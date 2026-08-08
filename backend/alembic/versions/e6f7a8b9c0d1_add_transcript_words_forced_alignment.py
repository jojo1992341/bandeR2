"""add_transcript_words_forced_alignment

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-07 18:50:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('transcript_words',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('segment_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('transcript_segments.id'), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('start_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('end_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('language', sa.String(length=10), server_default='fr'),
        sa.Column('confidence_score', sa.Numeric(4, 3), server_default='0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_transcript_words_segment_id', 'transcript_words', ['segment_id'])

def downgrade():
    op.drop_index('ix_transcript_words_segment_id', table_name='transcript_words')
    op.drop_table('transcript_words')
