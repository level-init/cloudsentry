"""Database session helpers."""

from collections.abc import Iterator
from os import environ

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def sqlalchemy_database_url() -> str:
    # Prefer TEST_DATABASE_URL so pytest can avoid the live Compose DB when set.
    url = environ.get("TEST_DATABASE_URL") or get_settings().database_url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def create_session() -> Session:
    engine = create_engine(sqlalchemy_database_url())
    factory = sessionmaker(bind=engine)
    return factory()


def get_session() -> Iterator[Session]:
    session = create_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
