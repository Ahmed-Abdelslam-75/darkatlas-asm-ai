"""Shared pytest fixtures.

The whole suite runs against an in-memory SQLite database (a StaticPool keeps it
alive across connections) so `pytest` works with no Postgres server and no API
key. The JSON columns fall back to generic JSON on SQLite (see models.py).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registers tables on Base
from app.db import Base


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
