"""Database session helpers."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def sqlalchemy_database_url() -> str:
    url = get_settings().database_url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def create_session() -> Session:
    engine = create_engine(sqlalchemy_database_url())
    factory = sessionmaker(bind=engine)
    return factory()
