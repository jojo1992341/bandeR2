"""add_comments"""
from alembic import op
import sqlalchemy as sa
revision = 'k3l4m5n6o7p8'
down_revision = 'j2k3l4m5n6o7'
branch_labels = None
depends_on = None
def upgrade():
    op.create_table('comments',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('replica_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('replicas.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('author_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

def downgrade():
    op.drop_table('comments')
