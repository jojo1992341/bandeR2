"""add sso configuration §15.2

Revision ID: x5y6z7a8b9c0
Revises: w4x5y6z7a8b9
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "x5y6z7a8b9c0"
down_revision = "w4x5y6z7a8b9"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "sso_configurations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("studio_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="generic"),
        sa.Column("protocol", sa.String(length=20), nullable=False, server_default="oidc"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("entity_id", sa.String(length=255), nullable=True),
        sa.Column("acs_url", sa.Text(), nullable=True),
        sa.Column("idp_entity_id", sa.Text(), nullable=True),
        sa.Column("idp_sso_url", sa.Text(), nullable=True),
        sa.Column("idp_x509_cert", sa.Text(), nullable=True),
        sa.Column("idp_metadata_url", sa.Text(), nullable=True),
        sa.Column("sp_x509_cert", sa.Text(), nullable=True),
        sa.Column("sp_private_key", sa.Text(), nullable=True),
        sa.Column("name_id_format", sa.String(length=100), nullable=True),
        sa.Column("attribute_mapping", sa.JSON(), nullable=True),
        sa.Column("issuer", sa.Text(), nullable=True),
        sa.Column("client_id", sa.String(length=255), nullable=True),
        sa.Column("client_secret", sa.Text(), nullable=True),
        sa.Column("authorization_endpoint", sa.Text(), nullable=True),
        sa.Column("token_endpoint", sa.Text(), nullable=True),
        sa.Column("jwks_uri", sa.Text(), nullable=True),
        sa.Column("userinfo_endpoint", sa.Text(), nullable=True),
        sa.Column("redirect_uri", sa.Text(), nullable=True),
        sa.Column("scopes", sa.String(length=255), nullable=True),
        sa.Column("oidc_attribute_mapping", sa.JSON(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["studio_id"], ["studios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("studio_id", name="uq_sso_studio"),
    )
    op.create_index(op.f("ix_sso_configurations_studio_id"), "sso_configurations", ["studio_id"], unique=True)

def downgrade() -> None:
    op.drop_index(op.f("ix_sso_configurations_studio_id"), table_name="sso_configurations")
    op.drop_table("sso_configurations")
