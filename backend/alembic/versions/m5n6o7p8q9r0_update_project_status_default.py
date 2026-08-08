"""update project status default to Cree §16.1

Revision ID: m5n6o7p8q9r0
Revises: l4m5n6o7p8q9
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "m5n6o7p8q9r0"
down_revision = "l4m5n6o7p8q9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migrate existing "draft" values to "Cree"
    op.execute("UPDATE projects SET status = 'Cree' WHERE status = 'draft'")
    # Update default value
    op.alter_column(
        "projects",
        "status",
        server_default="Cree",
    )


def downgrade() -> None:
    op.execute("UPDATE projects SET status = 'draft' WHERE status = 'Cree'")
    op.alter_column(
        "projects",
        "status",
        server_default="draft",
    )
