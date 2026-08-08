"""add_proxy_sprite_media

Revision ID: b2c3d4e5f6g7
Revises: 50f7d2a5adb0
Create Date: 2026-08-07 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = '50f7d2a5adb0'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('media_assets', sa.Column('proxy_path', sa.String(length=500), nullable=True))
    op.add_column('media_assets', sa.Column('sprite_sheet_path', sa.String(length=500), nullable=True))

def downgrade() -> None:
    op.drop_column('media_assets', 'proxy_path')
    op.drop_column('media_assets', 'sprite_sheet_path')
