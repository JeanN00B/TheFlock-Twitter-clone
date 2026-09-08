"""Live PostgreSQL HTTP evidence for authenticated tweet-like mutations."""

import os
from datetime import datetime, timezone
from uuid import UUID

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; PostgreSQL tweet-like HTTP tests skipped",
        allow_module_level=True,
    )
try:
    _database_url = make_url(TEST_DATABASE_URL)
except (ArgumentError, TypeError, ValueError):
    raise RuntimeError("TEST_DATABASE_URL must be a valid PostgreSQL URL") from None
if _database_url.get_backend_name() != "postgresql":
    raise RuntimeError("TEST_DATABASE_URL must use a PostgreSQL URL")

from app.auth.infrastructure.session_model import SessionModel  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.infrastructure.database import get_engine, get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.tweets.infrastructure.tweet_like_model import TweetLikeModel  # noqa: E402
from app.tweets.infrastructure.tweet_like_repository import (  # noqa: E402
    SQLAlchemyTweetLikeRepository,
)
from app.tweets.infrastructure.tweet_model import TweetModel  # noqa: E402
from app.users.infrastructure.follow_relationship_model import (  # noqa: E402
    FollowRelationshipModel,
)
from app.users.infrastructure.user_model import UserModel  # noqa: E402

PASSWORD = "like HTTP password"
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _alembic_config() -> AlembicConfig:
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


def _clear_rows(engine) -> None:
    with Session(engine) as session:
        session.execute(delete(TweetLikeModel))
        session.execute(delete(FollowRelationshipModel))
        session.execute(delete(TweetModel))
        session.execute(delete(SessionModel))
        session.execute(delete(UserModel))
        session.commit()


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


@pytest.fixture()
def runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
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


def _register_and_login(client: TestClient, username: str) -> UUID:
    registration = client.post(
        "/auth/register",
        json={
            "email": f"{username}@example.com",
            "username": username,
            "display_name": username.replace("_", " ").title(),
            "password": PASSWORD,
        },
    )
    assert registration.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": f"{username}@example.com", "password": PASSWORD},
    )
    assert login.status_code == 204
    return UUID(registration.json()["id"])


def test_like_http_is_exact_idempotent_self_allowed_and_body_ignored(client, runtime) -> None:
    actor_id = _register_and_login(client, "like_author")
    tweet_id = client.post("/tweets", json={"text": "like me"}).json()["id"]

    first = client.post(
        f"/tweets/{tweet_id}/like",
        json={"actor_id": "caller-controlled", "like_count": 999, "liked": False},
    )
    repeated = client.post(
        f"/tweets/{tweet_id}/like",
        content=b'{"ignored":',
        headers={"content-type": "application/json"},
    )
    unlike = client.request(
        "DELETE", f"/tweets/{tweet_id}/like", json={"liked": True, "actor_id": "other"}
    )
    repeated_unlike = client.delete(f"/tweets/{tweet_id}/like")

    expected = {"tweet_id": tweet_id, "like_count": 1, "liked_by_actor": True}
    assert first.status_code == repeated.status_code == 200
    assert first.json() == repeated.json() == expected
    assert set(first.json()) == {"tweet_id", "like_count", "liked_by_actor"}
    assert unlike.status_code == repeated_unlike.status_code == 200
    assert unlike.json() == repeated_unlike.json() == {
        "tweet_id": tweet_id,
        "like_count": 0,
        "liked_by_actor": False,
    }
    assert first.status_code not in {403, 409}
    with Session(runtime) as session:
        assert session.execute(select(TweetLikeModel)).scalars().all() == []
        assert session.execute(select(TweetModel).where(TweetModel.author_public_id == actor_id)).scalar_one()


def test_like_http_auth_and_canonical_validation_precede_disclosure(client) -> None:
    valid = "22222222-2222-4222-8222-222222222222"
    engine = get_engine()
    statements: list[str] = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.split()).lower())

    event.listen(engine, "before_cursor_execute", record)
    try:
        unauthenticated = [
            client.post(f"/tweets/{valid}/like"),
            client.delete("/tweets/not-a-uuid/like"),
        ]
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert [response.status_code for response in unauthenticated] == [401, 401]
    assert all(response.json() == {"error": {"code": "unauthenticated"}} for response in unauthenticated)
    assert not any("from tweets" in statement or "tweet_likes" in statement for statement in statements)

    _register_and_login(client, "canonical_actor")
    invalid_ids = [
        "abcdefab-cdef-4abc-8def-abcdefabcdef".upper(),
        valid.replace("-", ""),
        f" {valid} ",
        "22222222-2222-1222-8222-222222222222",
        "not-a-uuid",
    ]
    statements.clear()
    event.listen(engine, "before_cursor_execute", record)
    try:
        for invalid_id in invalid_ids:
            for method in ("post", "delete"):
                response = getattr(client, method)(f"/tweets/{invalid_id}/like")
                assert response.status_code == 422
                assert response.json() == {
                    "error": {"code": "validation_error", "fields": {"tweet_id": "invalid"}}
                }
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert not any("from tweets" in statement or "tweet_likes" in statement for statement in statements)


def test_like_http_unknown_and_soft_deleted_targets_share_exact_404(client, runtime) -> None:
    _register_and_login(client, "deleted_actor")
    unknown_id = "33333333-3333-4333-8333-333333333333"
    for method in ("post", "delete"):
        response = getattr(client, method)(f"/tweets/{unknown_id}/like")
        assert response.status_code == 404
        assert response.json() == {"error": {"code": "not_found"}}

    deleted_id = client.post("/tweets", json={"text": "retained like"}).json()["id"]
    assert client.post(f"/tweets/{deleted_id}/like").status_code == 200
    assert client.delete(f"/tweets/{deleted_id}").status_code == 204
    for method in ("post", "delete"):
        response = getattr(client, method)(f"/tweets/{deleted_id}/like")
        assert response.status_code == 404
        assert response.json() == {"error": {"code": "not_found"}}
    with Session(runtime) as session:
        rows = session.execute(select(TweetLikeModel)).scalars().all()
        assert len(rows) == 1
        assert rows[0].tweet_public_id == UUID(deleted_id)


def test_like_http_rolls_back_handled_failure_and_reuses_session(client, monkeypatch) -> None:
    _register_and_login(client, "failure_actor")
    tweet_id = client.post("/tweets", json={"text": "retry me"}).json()["id"]
    original = SQLAlchemyTweetLikeRepository.set_state
    failed = True

    def fail_once(repository, target_id, actor_id, liked):
        nonlocal failed
        if failed:
            failed = False
            raise RuntimeError("injected like failure")
        return original(repository, target_id, actor_id, liked)

    monkeypatch.setattr(SQLAlchemyTweetLikeRepository, "set_state", fail_once)
    failed_response = client.post(f"/tweets/{tweet_id}/like")
    retried_response = client.post(f"/tweets/{tweet_id}/like")

    assert failed_response.status_code == 500
    assert retried_response.status_code == 200
    assert retried_response.json() == {
        "tweet_id": tweet_id,
        "like_count": 1,
        "liked_by_actor": True,
    }
    assert retried_response.status_code not in {403, 409}
