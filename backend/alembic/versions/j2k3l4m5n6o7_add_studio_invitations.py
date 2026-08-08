"""add_studio_invitations"""
from alembic import op
import sqlalchemy as sa
revision = 'j2k3l4m5n6o7'
down_revision = 'i2j3k4l5m6n7'
branch_labels = None
depends_on = None
def upgrade():
    op.create_table('studio_invitations',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('studio_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('studios.id'), nullable=False, index=True),
        sa.Column('email', sa.String(length=255), nullable=False, index=True),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('token', sa.String(length=500), nullable=False, unique=True, index=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('is_accepted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_studio_invitations_studio_id', 'studio_invitations', ['studio_id'])
    op.create_index('ix_studio_invitations_email', 'studio_invitations', ['email'])

def downgrade():
    op.drop_index('ix_studio_invitations_email', table_name='studio_invitations')
    op.drop_index('ix_studio_invitations_studio_id', table_name='studio_invitations')
    op.drop_table('studio_invitations')
