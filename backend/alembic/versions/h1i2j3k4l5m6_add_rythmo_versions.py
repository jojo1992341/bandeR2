"""add_rythmo_versions"""
from alembic import op
import sqlalchemy as sa
revision = 'h1i2j3k4l5m6'
down_revision = 'g0h1i2j3k4l5'
branch_labels = None
depends_on = None
def upgrade():
    op.create_table('rythmo_versions',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id'), nullable=False, index=True),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=255), server_default='system'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_rythmo_versions_version_number', 'rythmo_versions', ['version_number'])
    op.create_unique_constraint('uq_project_version', 'rythmo_versions', ['project_id', 'version_number'])

def downgrade():
    op.drop_constraint('uq_project_version', 'rythmo_versions', type_='unique')
    op.drop_index('ix_rythmo_versions_version_number', table_name='rythmo_versions')
    op.drop_index('ix_rythmo_versions_project_id', table_name='rythmo_versions')
    op.drop_table('rythmo_versions')
