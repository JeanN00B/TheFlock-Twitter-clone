"""Live PostgreSQL HTTP contract for login and regression behavior."""

import base64
import hashlib
import os
from datetime import timedelta
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from uuid import UUID

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session as DBSession

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; PostgreSQL integration test skipped",
        allow_module_level=True,
    )

from app.auth.infrastructure.login_router import LoginRequest  # noqa: E402
from app.auth.infrastructure.origin_middleware import LoginOriginMiddleware  # noqa: E402
from app.auth.infrastructure.session_model import SessionModel  # noqa: E402
from app.auth.infrastructure.session_store import SQLAlchemySessionStore  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.infrastructure.database import get_engine, get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.users.infrastructure.user_model import UserModel  # noqa: E402

ALLOWED_ORIGIN = "http://localhost:3000"
HTTPS_ORIGIN = "https://frontend.example"
LOGIN_PASSWORD = "  exact login password  "

def _alembic_config() -> AlembicConfig:
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config

def _clear_rows(engine) -> None:
    with DBSession(engine) as session:
        session.execute(delete(SessionModel))
        session.execute(delete(UserModel))
        session.commit()

def _configure_login_origins(origins: tuple[str, ...]) -> None:
    for middleware in app.user_middleware:
        if middleware.cls is LoginOriginMiddleware:
            middleware.kwargs["allowed_origins"] = origins
    app.middleware_stack = None

@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    alembic_command.upgrade(_alembic_config(), "head")
    patch.undo()
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    yield
    engine = create_engine(TEST_DATABASE_URL)
    try:
        _clear_rows(engine)
    finally:
        engine.dispose()

@pytest.fixture()
def runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv("NEXT_PUBLIC_APP_URL", ALLOWED_ORIGIN)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    _configure_login_origins((ALLOWED_ORIGIN,))
    engine = create_engine(TEST_DATABASE_URL)
    _clear_rows(engine)
    try:
        yield engine
    finally:
        _clear_rows(engine)
        engine.dispose()
        get_settings.cache_clear()
        get_engine.cache_clear()
        get_session_factory.cache_clear()

@pytest.fixture()
def client(runtime):
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

def _register(client: TestClient, *, password: str = LOGIN_PASSWORD) -> UUID:
    response = client.post(
        "/auth/register",
        json={
            "email": "person+tag@example.com",
            "username": "alice_42",
            "display_name": "Alice Example",
            "password": password,
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])

def _cookie(response):
    values = response.headers.get_list("set-cookie")
    assert len(values) == 1
    parsed = SimpleCookie()
    parsed.load(values[0])
    assert set(parsed) == {"flock_session"}
    return parsed["flock_session"]

def _cookie_token(response) -> tuple[bytes, object]:
    morsel = _cookie(response)
    encoded = morsel.value
    assert len(encoded) == 43
    assert "=" not in encoded
    raw_token = base64.urlsafe_b64decode(encoded + "=")
    assert len(raw_token) == 32
    return raw_token, morsel

def _assert_allowed_cors(response) -> None:
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "origin" in {
        value.strip().lower()
        for value in response.headers.get("vary", "").split(",")
    }

def test_valid_registration_then_login_is_empty_and_digest_only(
    client: TestClient, runtime
) -> None:
    user_public_id = _register(client)
    response = client.post(
        "/auth/login",
        json={"email": "  Person+Tag@Example.COM  ", "password": LOGIN_PASSWORD},
    )

    assert response.status_code == 204
    assert response.content == b""
    raw_token, morsel = _cookie_token(response)
    assert morsel["path"] == "/"
    assert morsel["httponly"] == True
    assert morsel["samesite"] == "lax"
    assert morsel["max-age"] == "604800"
    assert morsel["domain"] == ""
    assert morsel["secure"] == ""
    assert LOGIN_PASSWORD not in response.text

    with DBSession(runtime) as session:
        user = session.execute(
            select(UserModel).where(UserModel.public_id == user_public_id)
        ).scalar_one()
        row = session.execute(select(SessionModel)).scalar_one()
        assert row.user_public_id == user_public_id
        assert len(row.token_hash) == 32
        assert row.token_hash == hashlib.sha256(raw_token).digest()
        assert row.expires_at - row.issued_at == timedelta(days=7)
        assert user.password_hash not in response.text
        cookie_expiry = parsedate_to_datetime(morsel["expires"])
        assert cookie_expiry == row.expires_at.replace(microsecond=0)
        assert session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 1

def test_two_successful_logins_create_independent_rows(client: TestClient, runtime) -> None:
    user_public_id = _register(client)
    first = client.post(
        "/auth/login", json={"email": "person+tag@example.com", "password": LOGIN_PASSWORD}
    )
    second = client.post(
        "/auth/login", json={"email": "person+tag@example.com", "password": LOGIN_PASSWORD}
    )

    first_token, _ = _cookie_token(first)
    second_token, _ = _cookie_token(second)
    assert first_token != second_token
    with DBSession(runtime) as session:
        rows = session.execute(
            select(SessionModel).where(SessionModel.user_public_id == user_public_id)
        ).scalars().all()
        assert len(rows) == 2
        assert len({row.token_hash for row in rows}) == 2
        assert {row.token_hash for row in rows} == {
            hashlib.sha256(first_token).digest(),
            hashlib.sha256(second_token).digest(),
        }

def test_absent_and_wrong_credentials_are_identical_and_cookie_free(
    client: TestClient, runtime
) -> None:
    _register(client)
    absent = client.post(
        "/auth/login",
        json={"email": "missing@example.com", "password": LOGIN_PASSWORD},
    )
    wrong = client.post(
        "/auth/login",
        json={"email": "person+tag@example.com", "password": "wrong password"},
    )

    assert absent.status_code == wrong.status_code == 401
    assert absent.json() == wrong.json() == {"error": {"code": "invalid_credentials"}}
    assert absent.headers.get_list("set-cookie") == []
    assert wrong.headers.get_list("set-cookie") == []
    with DBSession(runtime) as session:
        assert session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 0

@pytest.mark.parametrize(
    ("content", "expected_fields"),
    [
        ("{", {"body": "invalid"}),
        ("null", {"body": "invalid"}),
        ("[]", {"body": "invalid"}),
        ('"text"', {"body": "invalid"}),
        ('{"email":"person@example.com"}', {"password": "invalid"}),
        (
            '{"email":"person@example.com","password":"x","extra":"invalid"}',
            {"extra": "invalid"},
        ),
        ('{"email":42,"password":"x"}', {"email": "invalid"}),
        ('{"email":"person@example.com","password":true}', {"password": "invalid"}),
    ],
)
def test_malformed_and_non_strict_requests_are_422_and_cookie_free(
    client: TestClient, content: str, expected_fields: dict[str, str]
) -> None:
    response = client.post(
        "/auth/login",
        content=content,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "fields": expected_fields}
    }
    assert response.headers.get_list("set-cookie") == []

def test_disallowed_origin_is_rejected_before_credential_lookup(client: TestClient) -> None:
    def lookup_must_not_run(*args, **kwargs):
        raise AssertionError("credential lookup ran before Origin denial")

    from app.users.infrastructure.credential_lookup import SQLAlchemyUserCredentialLookup

    original = SQLAlchemyUserCredentialLookup.find_by_canonical_email
    SQLAlchemyUserCredentialLookup.find_by_canonical_email = lookup_must_not_run
    try:
        response = client.post(
            "/auth/login",
            json={"email": "person@example.com", "password": LOGIN_PASSWORD},
            headers={"Origin": "https://untrusted.example"},
        )
    finally:
        SQLAlchemyUserCredentialLookup.find_by_canonical_email = original

    assert response.status_code == 403
    assert response.json() == {"error": {"code": "origin_not_allowed"}}
    assert response.headers.get("access-control-allow-origin") is None
    assert response.headers.get("access-control-allow-credentials") is None
    assert response.headers.get_list("set-cookie") == []

@pytest.mark.parametrize("outcome", ["success", "unauthorized", "validation", "failure"])
def test_allowed_origin_gets_cors_headers_on_every_login_outcome(
    client: TestClient, outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if outcome == "success":
        _register(client)
        response = client.post(
            "/auth/login",
            json={"email": "person+tag@example.com", "password": LOGIN_PASSWORD},
            headers={"Origin": ALLOWED_ORIGIN},
        )
    elif outcome == "unauthorized":
        response = client.post(
            "/auth/login",
            json={"email": "missing@example.com", "password": LOGIN_PASSWORD},
            headers={"Origin": ALLOWED_ORIGIN},
        )
    elif outcome == "validation":
        response = client.post(
            "/auth/login",
            json={"email": "person@example.com"},
            headers={"Origin": ALLOWED_ORIGIN},
        )
    else:
        _register(client)

        def fail_commit(self, session):
            raise RuntimeError("database password hash token details")

        monkeypatch.setattr(SQLAlchemySessionStore, "add_committed", fail_commit)
        response = client.post(
            "/auth/login",
            json={"email": "person+tag@example.com", "password": LOGIN_PASSWORD},
            headers={"Origin": ALLOWED_ORIGIN},
        )

    assert response.status_code in {204, 401, 422, 500}
    _assert_allowed_cors(response)
    assert "database password hash token details" not in response.text
    if outcome != "success":
        assert response.headers.get_list("set-cookie") == []

def test_missing_origin_has_no_cors_grant(client: TestClient) -> None:
    _register(client)
    response = client.post(
        "/auth/login",
        json={"email": "person+tag@example.com", "password": LOGIN_PASSWORD},
    )

    assert response.status_code == 204
    assert response.headers.get("access-control-allow-origin") is None
    assert response.headers.get("access-control-allow-credentials") is None
    assert response.headers.get("vary") is None

def test_valid_preflight_is_body_and_cookie_free(client: TestClient, runtime) -> None:
    response = client.options(
        "/auth/login",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-allow-methods"] == "POST"
    assert response.headers["access-control-allow-headers"] == "content-type"
    assert response.headers.get_list("set-cookie") == []
    with DBSession(runtime) as session:
        assert session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 0

def test_persistence_failure_is_generic_and_emits_no_cookie(
    client: TestClient, runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(client)

    def fail_commit(self, session):
        raise RuntimeError("password hash and raw token must stay private")

    monkeypatch.setattr(SQLAlchemySessionStore, "add_committed", fail_commit)
    response = client.post(
        "/auth/login",
        json={"email": "person+tag@example.com", "password": LOGIN_PASSWORD},
    )

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error"}}
    assert response.headers.get_list("set-cookie") == []
    assert "password hash" not in response.text
    assert "raw token" not in response.text
    with DBSession(runtime) as session:
        assert session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 0

def test_production_login_cookie_is_secure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("NEXT_PUBLIC_APP_URL", HTTPS_ORIGIN)
    get_settings.cache_clear()
    _register(client)

    response = client.post(
        "/auth/login",
        json={"email": "person+tag@example.com", "password": LOGIN_PASSWORD},
    )

    assert response.status_code == 204
    _, morsel = _cookie_token(response)
    assert morsel["secure"] == True

def test_registration_and_health_never_issue_sessions(client: TestClient, runtime) -> None:
    _register(client)
    client.cookies.set("flock_session", "opaque-placeholder")
    health = client.get("/health")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert health.headers.get_list("set-cookie") == []
    with DBSession(runtime) as session:
        assert session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 0

def test_login_request_model_is_exactly_two_strict_strings() -> None:
    assert set(LoginRequest.model_fields) == {"email", "password"}
    assert LoginRequest.model_fields["email"].annotation is str
    assert LoginRequest.model_fields["password"].annotation is str
