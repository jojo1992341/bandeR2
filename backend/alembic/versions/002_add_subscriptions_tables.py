"""
Ajout des tables de subscription (§9.2, US-053 CDC)

Tables créées:
- subscriptions: abonnements actifs des studios
- subscription_usages: compteurs de consommation par période
- subscription_history: historique des changements

Revision ID: 002_add_subscriptions_tables
Revises: 001_add_rythmo_bands_table
Create Date: 2026-08-09
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

revision = "002_add_subscriptions_tables"
down_revision = "001_add_rythmo_bands_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("studio_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("studios.id"), nullable=False, index=True),
        sa.Column("plan", sa.String(50), nullable=False, server_default=sa.text("'free'"), index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'active'"), index=True),
        sa.Column("billing_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("billing_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True, index=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("amount_before_tax", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("tax_rate", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0.2000")),
        sa.Column("overage_behavior", sa.String(50), nullable=False, server_default=sa.text("'block'")),
        sa.Column("metadata", sa.JSON(), nullable=True, server_default=sa.text("'{}'::jsonb")),
    )

    # Contraintes uniques
    op.create_unique_constraint(
        "uq_studio_active_subscription",
        "subscriptions",
        ["studio_id", "status"]
    )

    # Index sur la période de facturation
    op.create_index(
        "ix_subscription_billing_period",
        "subscriptions",
        ["billing_period_start", "billing_period_end"]
    )

    # Table subscription_usages
    op.create_table(
        "subscription_usages",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("subscription_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("subscriptions.id"), nullable=False, index=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ia_minutes_used", sa.Integer(), nullable=False, server_default=sa.text("0"), index=True),
        sa.Column("storage_bytes_used", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("projects_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("media_assets_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("replicas_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_billed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("billed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overage_minutes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("overage_storage_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("overage_projects", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("overage_replicas", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Index unique sur subscription_id + period_start
    op.create_index(
        "ix_subscription_usage_period",
        "subscription_usages",
        ["subscription_id", "period_start"],
        unique=True
    )

    # Table subscription_history
    op.create_table(
        "subscription_history",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("subscription_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("subscriptions.id"), nullable=False, index=True),
        sa.Column("event_type", sa.String(50), nullable=False, index=True),
        sa.Column("event_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("subscription_history")
    op.drop_table("subscription_usages")
    op.drop_table("subscriptions")
