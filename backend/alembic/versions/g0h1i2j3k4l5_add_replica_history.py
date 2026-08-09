"""add_replica_history"""
from alembic import op
import sqlalchemy as sa
revision = 'g0h1i2j3k4l5'
down_revision = 'f1a2b3c4d5e6'  # après la création de la table replicas
branch_labels = None
depends_on = None
def upgrade():
    op.create_table('replica_history',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('replica_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('replicas.id'), nullable=False, index=True),
        sa.Column('previous_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('previous_start_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('previous_end_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('previous_speaker_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('speakers.id'), nullable=True),
        sa.Column('updated_by', sa.String(length=255), server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

def downgrade():
    op.drop_table('replica_history')
