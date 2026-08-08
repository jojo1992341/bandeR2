"""add replica crdt §16.4

Revision ID: y6z7a8b9c0d1
Revises: x5y6z7a8b9c0
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "y6z7a8b9c0d1"
down_revision = "x5y6z7a8b9c0"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "replica_crdt_states",
        sa.Column("replica_id", sa.UUID(), nullable=False),
        sa.Column("characters", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("version_vector", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("clock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["replica_id"], ["replicas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("replica_id"),
    )
    op.create_table(
        "replica_crdt_operations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("replica_id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.String(length=100), nullable=False),
        sa.Column("counter", sa.Integer(), nullable=False),
        sa.Column("op_type", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("char", sa.String(length=1), nullable=True),
        sa.Column("pos_id", sa.JSON(), nullable=True),
        sa.Column("version_vector", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("timestamp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["replica_id"], ["replicas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_replica_crdt_operations_replica_id"), "replica_crdt_operations", ["replica_id"], unique=False)
    op.create_index(op.f("ix_replica_crdt_operations_site_id"), "replica_crdt_operations", ["site_id"], unique=False)

def downgrade() -> None:
    op.drop_index(op.f("ix_replica_crdt_operations_site_id"), table_name="replica_crdt_operations")
    op.drop_index(op.f("ix_replica_crdt_operations_replica_id"), table_name="replica_crdt_operations")
    op.drop_table("replica_crdt_operations")
    op.drop_table("replica_crdt_states")
