"""Live PostgreSQL HTTP contract for protected sessions."""

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from uuid import UUID, uuid4

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

from app.auth.infrastructure.session_model import SessionModel  # noqa: E402
from app.auth.infrastructure.session_store import SQLAlchemySessionStore  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.infrastructure.database import get_engine, get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.users.infrastructure.user_model import UserModel  # noqa: E402


ALLOWED_ORIGIN = "http://localhost:3000"
PASSWORD = "exact protected-session password"
SESSION_COOKIE_NAME = "flock_session"


def _alembic_config() -> AlembicConfig:
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


def _clear_rows(engine) -> None:
    with DBSession(engine) as session:
        session.execute(delete(SessionModel))
        session.execute(delete(UserModel))
        session.commit()


@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    try:
        alembic_command.upgrade(_alembic_config(), "head")
    finally:
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


def _register(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={
            "email": "person+session@example.com",
            "username": "session_user",
            "display_name": "Session User",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201
    return response.json()


def _cookie_morsel(response):
    values = response.headers.get_list("set-cookie")
    assert len(values) == 1
    parsed = SimpleCookie()
    parsed.load(values[0])
    assert set(parsed) == {SESSION_COOKIE_NAME}
    return parsed[SESSION_COOKIE_NAME], values[0]


def _login(client: TestClient) -> tuple[dict[str, str], bytes, str]:
    registered = _register(client)
    response = client.post(
        "/auth/login",
        json={"email": registered["email"], "password": PASSWORD},
    )
    assert response.status_code == 204
    assert response.content == b""
    morsel, _ = _cookie_morsel(response)
    encoded_token = morsel.value
    assert len(encoded_token) == 43
    raw_token = base64.urlsafe_b64decode(encoded_token + "=")
    assert len(raw_token) == 32
    return registered, raw_token, encoded_token


def _assert_allowed_cors(response) -> None:
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "origin" in {
        value.strip().lower()
        for value in response.headers.get("vary", "").split(",")
    }


def _assert_unauthenticated(response) -> None:
    assert response.status_code == 401
    assert response.content == b'{"error":{"code":"unauthenticated"}}'
    assert response.json() == {"error": {"code": "unauthenticated"}}


def _assert_cookie_deleted(
    response, *, expected_status: int = 204, expected_content: bytes = b""
) -> None:
    assert response.status_code == expected_status
    assert response.content == expected_content
    morsel, header = _cookie_morsel(response)
    assert morsel.value == ""
    assert morsel["path"] == "/"
    assert morsel["domain"] == ""
    assert "Domain=" not in header
    assert morsel["max-age"] == "0"
    assert parsedate_to_datetime(morsel["expires"]) <= datetime.now(
        timezone.utc
    ) + timedelta(seconds=5)
    assert morsel["httponly"] == True
    assert morsel["samesite"] == "lax"


def _seed_session(
    engine,
    *,
    raw_token: bytes,
    expires_at: datetime,
    revoke: bool = False,
) -> str:
    user_public_id = uuid4()
    token_hash = hashlib.sha256(raw_token).digest()
    assert len(raw_token) == 32
    with DBSession(engine) as session:
        session.add(
            UserModel(
                public_id=user_public_id,
                email=f"{user_public_id.hex}@example.com",
                username=f"u_{user_public_id.hex[:10]}",
                display_name="Seeded Session User",
                password_hash="seeded-password-hash",
                created_at=expires_at - timedelta(days=7),
                updated_at=expires_at - timedelta(days=7),
            )
        )
        session.commit()
        session.add(
            SessionModel(
                token_hash=token_hash,
                user_public_id=user_public_id,
                issued_at=expires_at - timedelta(days=7),
                expires_at=expires_at,
            )
        )
        session.commit()
        if revoke:
            session.execute(
                delete(SessionModel).where(SessionModel.token_hash == token_hash)
            )
            session.commit()
    return base64.urlsafe_b64encode(raw_token).rstrip(b"=").decode("ascii")


def test_auth_me_returns_exact_public_user_without_secrets(client: TestClient, runtime) -> None:
    registered, raw_token, encoded_token = _login(client)

    response = client.get("/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id",
        "email",
        "username",
        "display_name",
        "created_at",
        "updated_at",
    }
    assert body["id"] == registered["id"]
    assert body["email"] == registered["email"]
    assert body["username"] == registered["username"]
    assert body["display_name"] == registered["display_name"]
    assert body["created_at"] == registered["created_at"]
    assert body["updated_at"] == registered["updated_at"]
    assert "password_hash" not in body
    assert "session" not in body

    with DBSession(runtime) as session:
        password_hash = session.execute(
            select(UserModel.password_hash).where(
                UserModel.public_id == UUID(registered["id"])
            )
        ).scalar_one()
    assert PASSWORD not in response.text
    assert password_hash not in response.text
    assert encoded_token not in response.text
    assert raw_token.hex() not in response.text


def test_auth_me_success_includes_allowed_cors_headers(client: TestClient) -> None:
    _login(client)

    response = client.get("/auth/me", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    _assert_allowed_cors(response)


@pytest.mark.parametrize("cookie", [None, "malformed-session-cookie"])
def test_auth_me_rejects_missing_or_malformed_cookie(
    client: TestClient, cookie: str | None
) -> None:
    if cookie is not None:
        client.cookies.set(SESSION_COOKIE_NAME, cookie)

    response = client.get("/auth/me")

    _assert_unauthenticated(response)
    assert "malformed-session-cookie" not in response.text


def test_expired_session_is_rejected_even_when_digest_row_exists(client: TestClient, runtime) -> None:
    raw_token = b"expired-session-token-0000000000"
    encoded_token = _seed_session(
        runtime,
        raw_token=raw_token,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    with DBSession(runtime) as session:
        assert session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 1

    client.cookies.set(SESSION_COOKIE_NAME, encoded_token)
    response = client.get("/auth/me")

    _assert_unauthenticated(response)
    assert encoded_token not in response.text
    assert raw_token.hex() not in response.text


def test_revoked_session_cookie_is_rejected(client: TestClient, runtime) -> None:
    raw_token = b"revoked-session-token-0000000000"
    encoded_token = _seed_session(
        runtime,
        raw_token=raw_token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        revoke=True,
    )
    with DBSession(runtime) as session:
        assert session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 0

    client.cookies.set(SESSION_COOKIE_NAME, encoded_token)
    response = client.get("/auth/me")

    _assert_unauthenticated(response)
    assert encoded_token not in response.text
    assert raw_token.hex() not in response.text


def test_valid_logout_is_empty_clears_cookie_revokes_session_and_ends_auth(
    client: TestClient, runtime
) -> None:
    registered, raw_token, encoded_token = _login(client)
    with DBSession(runtime) as session:
        token_hash = hashlib.sha256(raw_token).digest()
        assert session.execute(
            select(func.count()).select_from(SessionModel).where(
                SessionModel.token_hash == token_hash
            )
        ).scalar_one() == 1
        password_hash = session.execute(
            select(UserModel.password_hash).where(
                UserModel.public_id == UUID(registered["id"])
            )
        ).scalar_one()

    response = client.post("/auth/logout")

    _assert_cookie_deleted(response)
    assert password_hash not in response.text
    assert encoded_token not in response.text
    assert raw_token.hex() not in response.text
    with DBSession(runtime) as session:
        assert session.execute(
            select(func.count()).select_from(SessionModel).where(
                SessionModel.token_hash == token_hash
            )
        ).scalar_one() == 0

    subsequent = client.get("/auth/me")
    _assert_unauthenticated(subsequent)


@pytest.mark.parametrize("case", ["missing", "malformed", "repeated"])
def test_logout_is_idempotent_and_always_deletes_cookie(client: TestClient, case: str) -> None:
    if case == "malformed":
        client.cookies.set(SESSION_COOKIE_NAME, "malformed-session-cookie")
    elif case == "repeated":
        _, _, encoded_token = _login(client)
    else:
        encoded_token = None

    first = client.post("/auth/logout")
    _assert_cookie_deleted(first)

    if case == "repeated":
        client.cookies.set(SESSION_COOKIE_NAME, encoded_token)
        second = client.post("/auth/logout")
        _assert_cookie_deleted(second)


def test_logout_failure_is_generic_and_clears_cookie(
    client: TestClient, runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, raw_token, encoded_token = _login(client)

    def fail_revoke(self, token_digest) -> None:
        raise RuntimeError("password hash and raw session token must stay private")

    monkeypatch.setattr(SQLAlchemySessionStore, "revoke", fail_revoke)
    response = client.post("/auth/logout")

    assert response.status_code == 500
    assert response.content == b'{"error":{"code":"internal_error"}}'
    assert response.json() == {"error": {"code": "internal_error"}}
    _assert_cookie_deleted(
        response,
        expected_status=500,
        expected_content=b'{"error":{"code":"internal_error"}}',
    )
    assert "password hash" not in response.text
    assert "raw session token" not in response.text
    assert encoded_token not in response.text
    assert raw_token.hex() not in response.text
    with DBSession(runtime) as session:
        assert session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 1
