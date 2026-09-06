import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; PostgreSQL integration test skipped",
        allow_module_level=True,
    )

from app.core.settings import get_settings
from app.infrastructure.database import get_db, get_engine, get_session_factory


def test_database_adapter_executes_select_one(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    database_session = get_db()
    session = next(database_session)
    try:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        database_session.close()
