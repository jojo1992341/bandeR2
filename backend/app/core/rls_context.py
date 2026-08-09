"""Transaction-scoped PostgreSQL tenant context used by RLS policies."""
import uuid
from sqlalchemy import text
from sqlalchemy.orm import Session


def set_studio_context(db: Session, studio_id: uuid.UUID) -> None:
    """Set the tenant for the current transaction, never for the pooled session.

    PostgreSQL ``SET LOCAL`` is deliberately used: the value is automatically
    cleared at COMMIT/ROLLBACK, preventing tenant context leakage on pooled
    connections. RLS policies deny all rows when this setting is absent.
    """
    sid = uuid.UUID(str(studio_id))
    bind = db.get_bind()
    if bind and bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.current_studio_id', :sid, true)"), {"sid": str(sid)})
