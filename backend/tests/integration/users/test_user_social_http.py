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
from app.users.application.public_social_reads import (
    ProfileNotFound,
    ProfileValidationError,
    PublicIdentity,
    PublicProfile,
    RelationshipDirection,
    RelationshipPage,
    SearchValidationError,
)
from app.users.domain.user import PublicUser
from app.users.infrastructure.user_social_router import build_user_social_router

ACTOR_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
INSTANT = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


class RecordingSearch:
    def __init__(self) -> None:
        self.terms = []
        self.results = (PublicIdentity(ACTOR_ID, "alice_42", "Alice"),)

    def execute(self, term):
        if not isinstance(term, str) or not 1 <= len(term.strip()) <= 50:
            raise SearchValidationError()
        self.terms.append(term)
        return self.results


class RecordingProfile:
    def __init__(self) -> None:
        self.calls = []
        self.error = None
        self.result = PublicProfile(ACTOR_ID, "alice_42", "Alice", 3, 2, False)

    def execute(self, username, actor_id):
        self.calls.append((username, actor_id))
        if self.error:
            raise self.error
        return self.result


class RecordingRelationships:
    def __init__(self) -> None:
        self.calls = []
        self.result = RelationshipPage((PublicIdentity(ACTOR_ID, "alice_42", "Alice"),), None)

    def execute(self, username, direction, page_size, cursor):
        self.calls.append((username, direction, page_size, cursor))
        return self.result


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


def client_for(
    use_case: RecordingUseCase,
    authenticated: bool = True,
    search: RecordingSearch | None = None,
    profile: RecordingProfile | None = None,
    relationships: RecordingRelationships | None = None,
) -> TestClient:
    app = FastAPI()

    def current_user():
        if not authenticated:
            raise Unauthenticated()
        return actor()

    app.include_router(
        build_user_social_router(
            lambda: use_case,
            current_user,
            search_provider=lambda: search or RecordingSearch(),
            profile_provider=lambda: profile or RecordingProfile(),
            relationship_list_provider=lambda: relationships or RecordingRelationships(),
        )
    )

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


def test_search_route_requires_auth_and_returns_exact_public_envelope() -> None:
    follow = RecordingUseCase()
    search = RecordingSearch()
    with client_for(follow, search=search) as client:
        response = client.get("/users/search?q=%20Alice%20")

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"id": str(ACTOR_ID), "username": "alice_42", "display_name": "Alice"}]
    }
    assert search.terms == [" Alice "]
    assert "private@example.com" not in response.text


def test_search_rejects_missing_empty_repeated_and_too_long_q_without_call() -> None:
    follow = RecordingUseCase()
    search = RecordingSearch()
    with client_for(follow, search=search) as client:
        responses = [
            client.get("/users/search"),
            client.get("/users/search?q="),
            client.get("/users/search?q=a&q=b"),
            client.get("/users/search?q=" + "x" * 51),
        ]

    assert all(response.status_code == 422 for response in responses)
    assert all(response.json()["error"]["fields"] == {"q": "invalid"} for response in responses)
    assert search.terms == []


def test_search_authentication_precedes_query_validation_and_use_case() -> None:
    search = RecordingSearch()
    with client_for(RecordingUseCase(), authenticated=False, search=search) as client:
        response = client.get("/users/search")

    assert response.status_code == 401
    assert search.terms == []


def test_profile_returns_exact_projection_and_maps_errors() -> None:
    profile = RecordingProfile()
    with client_for(RecordingUseCase(), profile=profile) as client:
        response = client.get("/users/%20ALICE_42%20")
        profile.error = ProfileNotFound()
        missing = client.get("/users/missing_42")
        profile.error = ProfileValidationError()
        invalid = client.get("/users/a-")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(ACTOR_ID), "username": "alice_42", "display_name": "Alice",
        "followers_count": 3, "following_count": 2, "followed_by_actor": False,
    }
    assert profile.calls[0] == (" ALICE_42 ", ACTOR_ID)
    assert missing.json() == {"error": {"code": "not_found"}}
    assert invalid.json() == {
        "error": {"code": "validation_error", "fields": {"username": "invalid"}}
    }
    assert "private@example.com" not in response.text


def test_relationship_routes_return_exact_envelope_and_parse_page_size() -> None:
    relationships = RecordingRelationships()
    with client_for(RecordingUseCase(), relationships=relationships) as client:
        followers = client.get("/users/ALICE_42/followers?page_size=1")
        following = client.get("/users/alice_42/following")
        invalid = client.get("/users/alice_42/followers?page_size=1&page_size=2")
    assert followers.json() == {"items": [{"id": str(ACTOR_ID), "username": "alice_42", "display_name": "Alice"}], "next_cursor": None}
    assert following.status_code == 200
    assert relationships.calls[:2] == [
        ("ALICE_42", RelationshipDirection.FOLLOWERS, 1, None),
        ("alice_42", RelationshipDirection.FOLLOWING, 20, None),
    ]
    assert invalid.status_code == 422
    assert len(relationships.calls) == 2


def test_relationship_routes_reject_noncanonical_page_size_before_list_io() -> None:
    relationships = RecordingRelationships()
    with client_for(RecordingUseCase(), relationships=relationships) as client:
        responses = [client.get(
            f"/users/alice_42/followers?page_size={value}"
        ) for value in ("01", "%2B1", "%201")]
    assert all(response.status_code == 422 for response in responses)
    assert all(response.json()["error"]["fields"] == {"page_size": "invalid"} for response in responses)
    assert relationships.calls == []


def test_profile_authentication_precedes_target_resolution() -> None:
    profile = RecordingProfile()
    with client_for(RecordingUseCase(), authenticated=False, profile=profile) as client:
        response = client.get("/users/missing_42")

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthenticated"}}
    assert profile.calls == []


@pytest.fixture()
def live_social_runtime(monkeypatch: pytest.MonkeyPatch):
    import os

    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import delete, inspect
    from sqlalchemy.orm import Session

    from app.auth.infrastructure.session_model import SessionModel
    from app.core.settings import get_settings
    from app.infrastructure.database import get_engine, get_session_factory
    from app.tweets.infrastructure.tweet_like_model import TweetLikeModel
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

    from app.main import app

    engine = get_engine()

    def clear() -> None:
        with Session(engine) as session:
            if inspect(engine).has_table("tweet_likes"):
                session.execute(delete(TweetLikeModel))
            session.execute(delete(FollowRelationshipModel))
            session.execute(delete(TweetModel))
            session.execute(delete(SessionModel))
            session.execute(delete(UserModel))
            session.commit()

    clear()

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
def test_composed_search_is_literal_bounded_ordered_and_private_safe(live_social_runtime) -> None:
    app, engine = live_social_runtime
    with TestClient(app, raise_server_exceptions=False) as client:
        _register_and_login(client, "viewer_1")
        client.cookies.clear()
        _register_and_login(client, "ada_lovelace")
        client.cookies.clear()
        _register_and_login(client, "grace_hopper")
        for index in range(52):
            client.cookies.clear()
            _register_and_login(client, f"match_{index:02d}")

        from sqlalchemy import event, update
        from app.users.infrastructure.user_model import UserModel

        with Session(engine) as session:
            session.execute(
                update(UserModel).where(UserModel.username == "ada_lovelace")
                .values(display_name=r"Ada 100%_\ Literal")
            )
            session.commit()

        client.cookies.clear()
        assert client.post("/auth/login", json={
            "email": "viewer_1@example.com", "password": "valid password"
        }).status_code == 204
        statements: list[str] = []

        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", observe)
        try:
            invalid = client.get("/users/search?q=&q=x")
            assert not any("ILIKE" in statement for statement in statements)
            ada = client.get("/users/search?q=ADA")
            literal = client.get(r"/users/search?q=100%25_%5C")
            hopper = client.get("/users/search?q=hopper")
            capped = client.get("/users/search?q=match")
        finally:
            event.remove(engine, "before_cursor_execute", observe)

    assert invalid.status_code == 422
    assert ada.json()["items"][0]["username"] == "ada_lovelace"
    assert literal.json()["items"][0]["display_name"] == r"Ada 100%_\ Literal"
    assert hopper.json()["items"][0]["username"] == "grace_hopper"
    assert len(capped.json()["items"]) == 50
    assert [item["username"] for item in capped.json()["items"]] == [
        f"match_{index:02d}" for index in range(50)
    ]
    assert all(list(item) == ["id", "username", "display_name"] for item in capped.json()["items"])
    assert all("email" not in item and "password" not in item for item in capped.json()["items"])


@pytest.mark.integration
def test_composed_profile_is_one_statement_exact_and_viewer_relative(live_social_runtime) -> None:
    app, engine = live_social_runtime
    with TestClient(app, raise_server_exceptions=False) as client:
        actor_id = _register_and_login(client, "viewer_1")
        client.cookies.clear()
        target_id = _register_and_login(client, "target_1")
        client.cookies.clear()
        _register_and_login(client, "follower_1")
        assert client.post("/users/target_1/follow").status_code == 200
        client.cookies.clear()
        assert client.post("/auth/login", json={
            "email": "viewer_1@example.com", "password": "valid password"
        }).status_code == 204
        assert client.post("/users/target_1/follow").status_code == 200

        from sqlalchemy import event
        statements: list[str] = []
        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(engine, "before_cursor_execute", observe)
        try:
            target = client.get("/users/TARGET_1")
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        self_view = client.get("/users/viewer_1")
        missing = client.get("/users/missing_1")

    profile_statements = [statement for statement in statements if "follow_relationships" in statement]
    assert len(profile_statements) == 1
    assert "EXISTS" in profile_statements[0]
    assert target.status_code == 200
    assert target.json() == {
        "id": target_id, "username": "target_1", "display_name": "Target 1",
        "followers_count": 2, "following_count": 0, "followed_by_actor": True,
    }
    assert set(target.json()) == {
        "id", "username", "display_name", "followers_count", "following_count",
        "followed_by_actor",
    }
    assert self_view.json()["id"] == actor_id
    assert self_view.json()["followed_by_actor"] is False
    assert missing.status_code == 404


@pytest.mark.integration
def test_composed_relationship_lists_page_directions_and_isolate_cursors(live_social_runtime) -> None:
    app, engine = live_social_runtime
    with TestClient(app, raise_server_exceptions=False) as client:
        _register_and_login(client, "target_1")
        client.cookies.clear()
        _register_and_login(client, "follower_1")
        assert client.post("/users/target_1/follow").status_code == 200
        client.cookies.clear()
        _register_and_login(client, "follower_2")
        assert client.post("/users/target_1/follow").status_code == 200
        assert client.post("/users/follower_1/follow").status_code == 200

        first = client.get("/users/target_1/followers?page_size=1")
        cursor = first.json()["next_cursor"]
        second = client.get(f"/users/target_1/followers?page_size=1&cursor={cursor}")
        following = client.get("/users/follower_2/following")

        from sqlalchemy import event
        statements = []
        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(engine, "before_cursor_execute", observe)
        try:
            wrong_direction = client.get(f"/users/target_1/following?cursor={cursor}")
            wrong_target = client.get(f"/users/follower_1/followers?cursor={cursor}")
        finally:
            event.remove(engine, "before_cursor_execute", observe)

    assert first.status_code == second.status_code == following.status_code == 200
    assert [first.json()["items"][0]["username"], second.json()["items"][0]["username"]] == [
        "follower_2", "follower_1"
    ]
    assert [item["username"] for item in following.json()["items"]] == ["follower_1", "target_1"]
    assert all(set(item) == {"id", "username", "display_name"} for item in following.json()["items"])
    assert wrong_direction.status_code == wrong_target.status_code == 422
    assert not any("follow_relationships" in statement for statement in statements)


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
