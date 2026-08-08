"""add audit logs and security alerts

Revision ID: p8q9r0s1t2u3
Revises: o7p8q9r0s1t2
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "p8q9r0s1t2u3"
down_revision = "o7p8q9r0s1t2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("user_email", sa.String(length=255), nullable=True),
        sa.Column("studio_id", sa.UUID(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column(
            "country_code",
            sa.String(length=10),
            nullable=True,
            server_default=sa.text("'FR'"),
        ),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False
    )
    op.create_index(
        op.f("ix_audit_logs_created_at"),
        "audit_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_logs_studio_id"),
        "audit_logs",
        ["studio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"], unique=False
    )

    op.create_table(
        "security_alerts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("alert_type", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("user_email", sa.String(length=255), nullable=True),
        sa.Column("studio_id", sa.UUID(), nullable=True),
        sa.Column(
            "severity",
            sa.String(length=20),
            nullable=True,
            server_default=sa.text("'warning'"),
        ),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "is_resolved",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_security_alerts_alert_type"),
        "security_alerts",
        ["alert_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_alerts_created_at"),
        "security_alerts",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_alerts_studio_id"),
        "security_alerts",
        ["studio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_alerts_user_id"),
        "security_alerts",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("security_alerts")
    op.drop_table("audit_logs")
