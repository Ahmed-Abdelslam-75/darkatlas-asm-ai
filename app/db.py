"""Database engine, session factory, and the declarative Base.

We use a single SQLAlchemy engine with `pool_pre_ping` so stale connections
(common when Postgres starts a moment after the API in docker-compose) are
detected and recycled instead of raising on first use.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# Base class every ORM model inherits from.
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a request-scoped session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
