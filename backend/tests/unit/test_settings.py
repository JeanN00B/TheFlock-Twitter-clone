import pytest
from pydantic import ValidationError

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


def test_settings_parse_json_array_origins_and_secure_cookie_is_environment_derived(
    monkeypatch,
):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/test_db")
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", '["HTTPS://Frontend.Example:443"]')
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.app_environment == "production"
    assert settings.allowed_origins == ("https://frontend.example",)
    assert settings.session_cookie_secure is True


def test_local_empty_allowlist_is_valid_and_cookie_is_not_secure():
    settings = Settings(database_url="postgresql+psycopg://localhost/test_db")

    assert settings.app_environment == "local"
    assert settings.allowed_origins == ()
    assert settings.session_cookie_secure is False


def test_session_cookie_secure_is_read_only():
    settings = Settings(database_url="postgresql+psycopg://localhost/test_db")

    with pytest.raises((AttributeError, TypeError, ValueError)):
        settings.session_cookie_secure = True


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.com",
        "https://frontend.example/path",
        "https://frontend.example?next=/login",
        "https://frontend.example#fragment",
        "https://user:password@frontend.example",
        "https://frontend.example:bad",
        "https://frontend.example:",
        "ftp://frontend.example",
        "frontend.example",
        "null",
        "https://frontend.example/",
    ],
)
def test_settings_reject_non_exact_http_origins(origin):
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://localhost/test_db",
            allowed_origins=(origin,),
        )


def test_settings_reject_duplicate_origins_after_normalization():
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://localhost/test_db",
            allowed_origins=(
                "https://frontend.example",
                "HTTPS://FRONTEND.EXAMPLE:443",
            ),
        )


def test_production_with_empty_allowlist_fails_closed():
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://localhost/test_db",
            app_environment="production",
            allowed_origins=(),
        )


def test_settings_reject_unknown_environment():
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://localhost/test_db",
            app_environment="staging",
        )
