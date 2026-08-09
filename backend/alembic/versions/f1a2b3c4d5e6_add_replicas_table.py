"""add replicas base table §9.4

La table `replicas` (entité centrale §9.4) n'était créée par aucune migration :
la chaîne Alembic était donc inutilisable depuis `base` (les tests repoasaient
sur `create_all`). Cette migration corrige le trou en créant la table `replicas`
avec ses colonnes de base, **entre** `speakers` (f0a1b2c3d4e5) et
`replica_history` (g0h1i2j3k4l5) — `replicas` référence `media_assets` et
`speakers`, et est référencée par `replica_history`.

Les colonnes ajoutées ultérieurement par d'autres migrations (rythmo_band_id,
version, syllable_count, speech_rate, speech_rate_alert) et les index
(composite, order_index, GIN) ne sont PAS incluses ici : elles sont gérées par
leurs migrations respectives (001, l4m5, r0s1, 005).

Revision ID: f1a2b3c4d5e6
Revises: f0a1b2c3d4e5
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replicas",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "media_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id"),
            nullable=False,
        ),
        sa.Column(
            "speaker_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("speakers.id"),
            nullable=True,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("end_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("typo_codes", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column(
            "confidence_score",
            sa.Numeric(precision=4, scale=3),
            nullable=True,
            server_default="0",
        ),
        sa.Column(
            "is_manually_edited", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "breath_marker", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_replicas_media_id", "replicas", ["media_id"])
    op.create_index("ix_replicas_speaker_id", "replicas", ["speaker_id"])


def downgrade() -> None:
    op.drop_index("ix_replicas_speaker_id", table_name="replicas")
    op.drop_index("ix_replicas_media_id", table_name="replicas")
    op.drop_table("replicas")
