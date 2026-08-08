"""add_pipeline_jobs

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6g7
Create Date: 2026-08-07 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('pipeline_jobs',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='pending'),
        sa.Column('progress_percent', sa.Integer(), server_default='0'),
        sa.Column('current_step', sa.String(length=100), server_default='init'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()')),
    )
    op.create_index('ix_pipeline_jobs_project_id', 'pipeline_jobs', ['project_id'])

def downgrade():
    op.drop_index('ix_pipeline_jobs_project_id', table_name='pipeline_jobs')
    op.drop_table('pipeline_jobs')
