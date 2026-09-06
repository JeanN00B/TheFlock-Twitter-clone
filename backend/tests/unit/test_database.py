import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.infrastructure.database import get_db, get_engine, get_session_factory

pytestmark = pytest.mark.unit


@pytest.fixture
def sqlite_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    yield
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


def test_database_adapter_builds_cached_usable_engine_and_session_factory(
    sqlite_database,
):
    engine = get_engine()
    session_factory = get_session_factory()

    assert isinstance(engine, Engine)
    assert get_engine() is engine
    assert get_session_factory() is session_factory

    with session_factory() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_get_db_yields_a_usable_session_and_closes_it(sqlite_database):
    database_dependency = get_db()
    session = next(database_dependency)

    assert isinstance(session, Session)
    assert session.execute(text("SELECT 1")).scalar_one() == 1
    assert session.in_transaction()

    database_dependency.close()

    assert not session.in_transaction()
