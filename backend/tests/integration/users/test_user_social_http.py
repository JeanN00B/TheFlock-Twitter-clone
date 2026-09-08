"""HTTP adapter contract for follow and unfollow."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from app.auth.application.session_access import Unauthenticated
from app.users.application.follow_relationships import (
    FollowState,
    FollowValidationError,
    UserNotFound,
)
from app.users.domain.user import PublicUser
from app.users.infrastructure.user_social_router import build_user_social_router

ACTOR_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
INSTANT = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


class RecordingUseCase:
    def __init__(self) -> None:
        self.commands = []
        self.error = None

    def execute(self, command):
        self.commands.append(command)
        if self.error:
            raise self.error
        return FollowState(command.target_username.strip().lower(), command.following)


def actor() -> PublicUser:
    return PublicUser(
        ACTOR_ID,
        "private@example.com",
        "alice_42",
        "Alice",
        INSTANT,
        INSTANT,
    )


def client_for(use_case: RecordingUseCase, authenticated: bool = True) -> TestClient:
    app = FastAPI()

    def current_user():
        if not authenticated:
            raise Unauthenticated()
        return actor()

    app.include_router(build_user_social_router(lambda: use_case, current_user))

    @app.exception_handler(Unauthenticated)
    async def unauthenticated(_request, _error):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=401,
            content={"error": {"code": "unauthenticated"}},
        )

    return TestClient(app)


@pytest.mark.parametrize(("verb", "following"), [("post", True), ("delete", False)])
def test_routes_return_exact_public_state_and_pass_session_actor(
    verb: str, following: bool
) -> None:
    use_case = RecordingUseCase()
    with client_for(use_case) as client:
        response = getattr(client, verb)("/users/%20BoB_42%20/follow")

    assert response.status_code == 200
    assert response.json() == {"username": "bob_42", "following": following}
    assert list(response.json()) == ["username", "following"]
    command = use_case.commands[0]
    assert (command.actor_id, command.actor_username, command.following) == (
        ACTOR_ID,
        "alice_42",
        following,
    )
    assert not hasattr(command, "occurred_at")
    assert "private@example.com" not in response.text


def test_unknown_and_validation_errors_have_exact_envelopes() -> None:
    use_case = RecordingUseCase()
    with client_for(use_case) as client:
        use_case.error = UserNotFound()
        missing = client.post("/users/nobody/follow")
        use_case.error = FollowValidationError({"username": "invalid"})
        malformed = client.post("/users/a-/follow")
        use_case.error = FollowValidationError({"username": "self_follow"})
        self_follow = client.post("/users/alice_42/follow")

    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found"}}
    assert malformed.status_code == 422
    assert malformed.json() == {
        "error": {"code": "validation_error", "fields": {"username": "invalid"}}
    }
    assert self_follow.status_code == 422
    assert self_follow.json() == {
        "error": {
            "code": "validation_error",
            "fields": {"username": "self_follow"},
        }
    }


def test_missing_session_is_401_before_use_case() -> None:
    use_case = RecordingUseCase()
    with client_for(use_case, authenticated=False) as client:
        response = client.post("/users/bob_42/follow")

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthenticated"}}
    assert use_case.commands == []


@pytest.fixture()
def live_social_runtime(monkeypatch: pytest.MonkeyPatch):
    import os

    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import create_engine, delete
    from sqlalchemy.orm import Session

    from app.auth.infrastructure.session_model import SessionModel
    from app.core.settings import get_settings
    from app.infrastructure.database import get_engine, get_session_factory
    from app.tweets.infrastructure.tweet_model import TweetModel
    from app.users.infrastructure.follow_relationship_model import FollowRelationshipModel
    from app.users.infrastructure.user_model import UserModel

    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not set; PostgreSQL HTTP test skipped")

    try:
        _database_url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError):
        raise RuntimeError("TEST_DATABASE_URL must be a valid PostgreSQL URL") from None
    if _database_url.get_backend_name() != "postgresql":
        raise RuntimeError("TEST_DATABASE_URL must use a PostgreSQL URL")

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    alembic_command.upgrade(config, "e4f5a6b7c8d9")
    engine = create_engine(database_url)

    def clear() -> None:
        with Session(engine) as session:
            session.execute(delete(FollowRelationshipModel))
            session.execute(delete(TweetModel))
            session.execute(delete(SessionModel))
            session.execute(delete(UserModel))
            session.commit()

    clear()
    from app.main import app

    try:
        yield app, engine
    finally:
        clear()
        engine.dispose()
        get_settings.cache_clear()
        get_engine.cache_clear()
        get_session_factory.cache_clear()


def _register_and_login(client: TestClient, username: str) -> str:
    registration = client.post(
        "/auth/register",
        json={
            "email": f"{username}@example.com",
            "username": username,
            "display_name": username.replace("_", " ").title(),
            "password": "valid password",
        },
    )
    assert registration.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": f"{username}@example.com", "password": "valid password"},
    )
    assert login.status_code == 204
    return registration.json()["id"]


@pytest.mark.integration
def test_composed_follow_routes_persist_exact_idempotent_state(live_social_runtime) -> None:
    app, engine = live_social_runtime
    with TestClient(app, raise_server_exceptions=False) as client:
        _register_and_login(client, "alice_42")
        client.cookies.clear()
        _register_and_login(client, "bob_42")
        client.cookies.clear()
        login = client.post(
            "/auth/login",
            json={"email": "alice_42@example.com", "password": "valid password"},
        )
        assert login.status_code == 204

        followed = client.post("/users/bob_42/follow")
        repeated_follow = client.post("/users/bob_42/follow")
        unfollowed = client.delete("/users/bob_42/follow")
        repeated_unfollow = client.delete("/users/bob_42/follow")

    assert [response.status_code for response in (
        followed,
        repeated_follow,
        unfollowed,
        repeated_unfollow,
    )] == [200, 200, 200, 200]
    assert followed.json() == {"username": "bob_42", "following": True}
    assert repeated_follow.json() == followed.json()
    assert unfollowed.json() == {"username": "bob_42", "following": False}
    assert repeated_unfollow.json() == unfollowed.json()

    from sqlalchemy import func, select
    from app.users.infrastructure.follow_relationship_model import FollowRelationshipModel

    with Session(engine) as session:
        assert session.execute(
            select(func.count()).select_from(FollowRelationshipModel)
        ).scalar_one() == 0


@pytest.mark.integration
def test_composed_follow_routes_preserve_errors_authentication_and_privacy(
    live_social_runtime,
) -> None:
    app, _engine = live_social_runtime
    with TestClient(app, raise_server_exceptions=False) as client:
        _register_and_login(client, "alice_42")
        client.cookies.clear()
        _register_and_login(client, "bob_42")
        client.cookies.clear()
        login = client.post(
            "/auth/login",
            json={"email": "alice_42@example.com", "password": "valid password"},
        )
        assert login.status_code == 204

        self_follow = client.post("/users/alice_42/follow")
        self_unfollow = client.delete("/users/alice_42/follow")
        unknown = client.post("/users/unknown_42/follow")
        malformed = client.post("/users/a-/follow")
        assert self_unfollow.json() == {"username": "alice_42", "following": False}

        client.cookies.clear()
        unauthenticated = client.post("/users/bob_42/follow")

    assert self_follow.status_code == 422
    assert self_follow.json() == {
        "error": {"code": "validation_error", "fields": {"username": "self_follow"}}
    }
    assert self_unfollow.status_code == 200
    assert unknown.status_code == 404
    assert unknown.json() == {"error": {"code": "not_found"}}
    assert malformed.status_code == 422
    assert malformed.json() == {
        "error": {"code": "validation_error", "fields": {"username": "invalid"}}
    }
    assert unauthenticated.status_code == 401
    assert unauthenticated.json() == {"error": {"code": "unauthenticated"}}
    assert set(self_unfollow.json()) == {"username", "following"}
    assert "password" not in self_unfollow.text
    assert "email" not in self_unfollow.text
