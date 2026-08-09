"""
Ajout de l'entité RythmoBand (§9.2–§9.4 CDC)

Cette migration:
1. Crée la table rythmo_bands
2. Ajoute rythmo_band_id à la table replicas

Revision ID: 001_add_rythmo_bands_table
Revises: z7a8b9c0d1e2
Create Date: 2026-08-09
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "001_add_rythmo_bands_table"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Créer la table rythmo_bands (§9.2)
    op.create_table(
        "rythmo_bands",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("media_asset_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("media_assets.id"), nullable=True, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default=sa.text("1"), index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'draft'"), index=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("typographic_profile_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("typographic_profiles.id"), nullable=True, index=True),
        sa.Column("is_master", sa.Boolean(), nullable=False, server_default=sa.text("false"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True, server_default=sa.text("'{}'::jsonb")),
    )

    # Ajouter rythmo_band_id à la table replicas (§9.4)
    op.add_column(
        "replicas",
        sa.Column(
            "rythmo_band_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rythmo_bands.id"),
            nullable=True,
            index=True
        )
    )


def downgrade() -> None:
    # Supprimer rythmo_band_id de replicas
    op.drop_column("replicas", "rythmo_band_id")
    
    # Supprimer la table rythmo_bands
    op.drop_table("rythmo_bands")
