from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.config import get_settings

settings = get_settings()
url = settings.DATABASE_URL.replace("+asyncpg", "")
connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
engine_kwargs = {"future": True, "echo": False, "connect_args": connect_args}
if url.startswith("sqlite") and ":memory:" in url:
    engine_kwargs["poolclass"] = StaticPool

engine = create_engine(url, **engine_kwargs)

if url.startswith("sqlite"):
    from app.models import Base
    Base.metadata.create_all(bind=engine)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
