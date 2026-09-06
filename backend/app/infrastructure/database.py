"""Synchronous SQLAlchemy database infrastructure."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import get_settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Build and return the lazily cached runtime engine."""

    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Build and return the lazily cached synchronous session factory."""

    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for use as a FastAPI dependency."""

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
