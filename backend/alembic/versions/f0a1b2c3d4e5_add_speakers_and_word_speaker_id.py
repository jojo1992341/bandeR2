"""add_speakers_and_word_speaker_id

Revision ID: f0a1b2c3d4e5
Revises: e6f7a8b9c0d1
Create Date: 2026-08-07 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f0a1b2c3d4e5'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('speakers',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False, server_default='Locuteur'),
        sa.Column('color', sa.String(length=7), server_default='#e11d48'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_speakers_project_id', 'speakers', ['project_id'])
    op.add_column('transcript_words', sa.Column('speaker_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('speakers.id'), nullable=True))
    op.create_index('ix_transcript_words_speaker_id', 'transcript_words', ['speaker_id'])

def downgrade():
    op.drop_index('ix_transcript_words_speaker_id', table_name='transcript_words')
    op.drop_column('transcript_words', 'speaker_id')
    op.drop_index('ix_speakers_project_id', table_name='speakers')
    op.drop_table('speakers')
