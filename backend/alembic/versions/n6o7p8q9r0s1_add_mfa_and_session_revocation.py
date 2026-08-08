"""add mfa and session revocation

Revision ID: n6o7p8q9r0s1
Revises: m5n6o7p8q9r0
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "n6o7p8q9r0s1"
down_revision = "m5n6o7p8q9r0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "totp_enabled",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
