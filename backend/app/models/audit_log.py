import uuid
from sqlalchemy import String, JSON, DateTime, func, Boolean, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, Session
from .base import Base
from app.core.uuid7 import uuid7
from typing import Optional
from datetime import datetime


class AuditLog(Base):
    """
    Journal d'audit append-only et non modifiable des actions sensibles (§15.5)
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    user_email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    studio_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, default="127.0.0.1"
    )
    country_code: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, default="FR"
    )
    details: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


class AuditLogImmutableError(RuntimeError):
    """Exception raised when trying to modify or delete an append-only AuditLog entry (§15.5)."""

    pass


_ALLOW_AUDIT_LOG_PURGE = False


def set_allow_audit_log_purge(allow: bool):
    global _ALLOW_AUDIT_LOG_PURGE
    _ALLOW_AUDIT_LOG_PURGE = allow


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def block_audit_log_modification(mapper, connection, target):
    global _ALLOW_AUDIT_LOG_PURGE
    if not _ALLOW_AUDIT_LOG_PURGE:
        raise AuditLogImmutableError(
            "AuditLog is append-only and cannot be modified or deleted (§15.5)"
        )


@event.listens_for(Session, "before_flush")
def block_audit_log_session_modification(session, flush_context, instances):
    global _ALLOW_AUDIT_LOG_PURGE
    if not _ALLOW_AUDIT_LOG_PURGE:
        for obj in session.dirty:
            if isinstance(obj, AuditLog):
                raise AuditLogImmutableError(
                    "AuditLog is append-only and cannot be modified or deleted (§15.5)"
                )
        for obj in session.deleted:
            if isinstance(obj, AuditLog):
                raise AuditLogImmutableError(
                    "AuditLog is append-only and cannot be modified or deleted (§15.5)"
                )


@event.listens_for(Session, "do_orm_execute")
def block_audit_log_orm_execute(orm_execute_state):
    global _ALLOW_AUDIT_LOG_PURGE
    if not _ALLOW_AUDIT_LOG_PURGE:
        if (
            orm_execute_state.is_update or orm_execute_state.is_delete
        ) and orm_execute_state.all_mappers:
            for mapper in orm_execute_state.all_mappers:
                if mapper.class_ == AuditLog:
                    raise AuditLogImmutableError(
                        "AuditLog is append-only and cannot be modified or deleted (§15.5)"
                    )
