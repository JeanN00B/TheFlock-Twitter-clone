import pytest

from app.core.settings import Settings, get_settings

pytestmark = pytest.mark.unit


def test_settings_reads_database_url_from_environment(monkeypatch):
    database_url = "postgresql+psycopg://user:password@localhost/test_db"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_url == database_url
    assert get_settings() is settings


def test_settings_reads_database_url_from_dotenv(tmp_path):
    database_url = "postgresql+psycopg://user:password@localhost/dotenv_db"
    (tmp_path / ".env").write_text(f"DATABASE_URL={database_url}\n")

    settings = Settings(_env_file=tmp_path / ".env")

    assert settings.database_url == database_url
