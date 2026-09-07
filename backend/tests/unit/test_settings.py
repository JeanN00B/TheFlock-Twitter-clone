import pytest
from pydantic import ValidationError

from app.core.settings import Settings, get_frontend_origin, get_settings, normalize_origin

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_reads_database_url_and_auto_migrate_from_environment(monkeypatch):
    database_url = "postgresql+psycopg://user:password@localhost/test_db"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AUTO_MIGRATE", "true")

    settings = get_settings()

    assert settings.database_url == database_url
    assert settings.auto_migrate is True
    assert get_settings() is settings


def test_settings_reads_database_url_from_dotenv(monkeypatch, tmp_path):
    database_url = "postgresql+psycopg://user:password@localhost/dotenv_db"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text(f"DATABASE_URL={database_url}\n")

    settings = Settings(_env_file=tmp_path / ".env")

    assert settings.database_url == database_url
    assert settings.auto_migrate is False


def test_settings_cache_is_stable_until_cleared(monkeypatch):
    first_url = "postgresql+psycopg://localhost/first_db"
    second_url = "postgresql+psycopg://localhost/second_db"
    monkeypatch.setenv("DATABASE_URL", first_url)

    first = get_settings()
    monkeypatch.setenv("DATABASE_URL", second_url)

    assert get_settings() is first
    assert get_settings().database_url == first_url

    get_settings.cache_clear()
    refreshed = get_settings()

    assert refreshed is not first
    assert refreshed.database_url == second_url


@pytest.mark.parametrize(
    ("environment", "expected_secure"),
    [("development", False), ("production", True)],
)
def test_settings_supports_exact_environment_modes(environment, expected_secure):
    settings = Settings(
        database_url="postgresql+psycopg://localhost/test_db",
        app_environment=environment,
        next_public_app_url="https://frontend.example",
    )

    assert settings.app_environment == environment
    assert settings.session_cookie_secure is expected_secure


@pytest.mark.parametrize("environment", ["local", "test", "Development", ""])
def test_settings_rejects_non_contract_environment_modes(environment):
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://localhost/test_db",
            app_environment=environment,
        )


def test_next_public_app_url_defaults_and_normalizes():
    default_settings = Settings(database_url="postgresql+psycopg://localhost/test_db")
    normalized_settings = Settings(
        database_url="postgresql+psycopg://localhost/test_db",
        next_public_app_url="HTTPS://Frontend.Example:443",
    )

    assert default_settings.next_public_app_url == "http://localhost:3000"
    assert normalized_settings.next_public_app_url == "https://frontend.example"


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "ftp://frontend.example",
        "frontend.example",
        "https://frontend.example/path",
        "https://frontend.example?next=/login",
        "https://frontend.example#fragment",
        "https://user:password@frontend.example",
        "https://frontend.example:bad",
        "https://frontend.example:",
        "https://*.example.com",
    ],
)
def test_settings_rejects_invalid_next_public_app_url(origin):
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://localhost/test_db",
            next_public_app_url=origin,
        )


def test_production_rejects_a_non_https_browser_origin():
    with pytest.raises(ValidationError, match="production requires NEXT_PUBLIC_APP_URL to use HTTPS"):
        Settings(
            database_url="postgresql+psycopg://localhost/test_db",
            app_environment="production",
            next_public_app_url="http://frontend.example",
        )


def test_session_cookie_secure_is_read_only():
    settings = Settings(
        database_url="postgresql+psycopg://localhost/test_db",
        app_environment="production",
        next_public_app_url="https://frontend.example",
    )

    with pytest.raises(AttributeError):
        settings.session_cookie_secure = False


def test_settings_has_no_origin_allowlist_field():
    settings = Settings(database_url="postgresql+psycopg://localhost/test_db")

    assert "allowed_origins" not in Settings.model_fields
    assert not hasattr(settings, "allowed_origins")


def test_get_frontend_origin_is_import_safe_and_does_not_require_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_APP_URL", "HTTPS://Frontend.Example:443")

    assert get_frontend_origin() == "https://frontend.example"


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
def test_normalize_origin_rejects_non_exact_http_origins(origin):
    with pytest.raises(ValueError):
        normalize_origin(origin)
