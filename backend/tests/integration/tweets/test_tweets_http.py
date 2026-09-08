"""Live PostgreSQL HTTP evidence for authenticated tweet creation."""

import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; PostgreSQL tweet HTTP integration test skipped",
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
from app.tweets.infrastructure.tweet_model import TweetModel  # noqa: E402
from app.users.infrastructure.follow_relationship_model import (  # noqa: E402
    FollowRelationshipModel,
)
from app.users.infrastructure.user_model import UserModel  # noqa: E402

PASSWORD = "exact tweet creation password"


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


def _register_and_login(client: TestClient, name: str = "tweet_author") -> UUID:
    registration = client.post(
        "/auth/register",
        json={
            "email": f"{name}@example.com",
            "username": name,
            "display_name": name.replace("_", " ").title(),
            "password": PASSWORD,
        },
    )
    assert registration.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": f"{name}@example.com", "password": PASSWORD},
    )
    assert login.status_code == 204
    return UUID(registration.json()["id"])


def test_create_commits_actor_owned_exact_public_tweet(client: TestClient, runtime) -> None:
    actor_id = _register_and_login(client)

    first = client.post("/tweets", json={"text": "  hello  world\n  "})
    second = client.post("/tweets", json={"text": "🙂" * 280})

    assert first.status_code == second.status_code == 201
    assert first.json()["text"] == "hello  world"
    assert set(first.json()) == {"id", "text", "created_at", "author", "like_count", "liked_by_actor"}
    assert first.json()["like_count"] == 0
    assert first.json()["liked_by_actor"] is False
    assert first.json()["author"] == {
        "id": str(actor_id),
        "username": "tweet_author",
        "display_name": "Tweet Author",
    }
    assert UUID(first.json()["id"]).version == 4
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["created_at"].endswith("Z")
    assert not any(secret in first.text for secret in ("tweet-author@example.com", PASSWORD, "deleted_at", "updated_at", "public_id"))

    with Session(runtime) as session:
        rows = session.execute(select(TweetModel).order_by(TweetModel.created_at)).scalars().all()
        assert len(rows) == 2
        assert rows[0].author_public_id == actor_id
        assert rows[0].text == "hello  world"
        assert rows[0].created_at == rows[0].updated_at
        assert rows[0].deleted_at is None


@pytest.mark.parametrize(
    "payload",
    [{}, {"text": None}, {"text": 1}, {"text": []}, {"text": ""}, {"text": "x" * 281}, {"text": "ok", "id": "caller"}],
)
def test_create_rejects_invalid_body_without_insert(client: TestClient, runtime, payload) -> None:
    _register_and_login(client)

    response = client.post("/tweets", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    with Session(runtime) as session:
        assert session.execute(select(TweetModel)).scalars().all() == []


def test_create_preserves_unauthenticated_envelope(client: TestClient, runtime) -> None:
    response = client.post("/tweets", json={"text": "hello"})

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthenticated"}}
    with Session(runtime) as session:
        assert session.execute(select(TweetModel)).scalars().all() == []


def test_feed_is_global_tied_order_exact_and_one_joined_query(client: TestClient, runtime) -> None:
    _register_and_login(client, "first_author")
    first = client.post("/tweets", json={"text": "first"}).json()
    _register_and_login(client, "second_author")
    second = client.post("/tweets", json={"text": "second"}).json()
    tied = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    with Session(runtime) as session:
        session.execute(update(TweetModel).values(created_at=tied, updated_at=tied))
        session.commit()

    statements = []
    def count(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    app_engine = get_engine()
    event.listen(app_engine, "before_cursor_execute", count)
    response = client.get("/tweets?page_size=50")
    event.remove(app_engine, "before_cursor_execute", count)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "next_cursor"}
    assert [item["id"] for item in body["items"]] == sorted([first["id"], second["id"]], reverse=True)
    assert {item["author"]["username"] for item in body["items"]} == {"first_author", "second_author"}
    assert all(
        set(item) == {"id", "text", "created_at", "author", "like_count", "liked_by_actor"}
        for item in body["items"]
    )
    assert all(item["like_count"] == 0 and item["liked_by_actor"] is False for item in body["items"])
    assert all(set(item["author"]) == {"id", "username", "display_name"} for item in body["items"])
    assert body["next_cursor"] is None
    assert sum("FROM tweets JOIN users" in " ".join(statement.split()) for statement in statements) == 1


def test_feed_like_fields_are_actor_relative_and_do_not_alter_cursor_membership(
    client: TestClient,
) -> None:
    _register_and_login(client, "like_viewer")
    first = client.post("/tweets", json={"text": "alpha"}).json()
    second = client.post("/tweets", json={"text": "beta"}).json()
    assert first["like_count"] == 0 and first["liked_by_actor"] is False

    liked = client.post(f"/tweets/{first['id']}/like")
    assert liked.status_code == 200
    assert liked.json() == {
        "tweet_id": first["id"],
        "like_count": 1,
        "liked_by_actor": True,
    }

    page_one = client.get("/tweets?page_size=1")
    assert page_one.status_code == 200
    assert page_one.json()["items"][0]["id"] == second["id"]
    assert page_one.json()["items"][0]["like_count"] == 0
    assert page_one.json()["items"][0]["liked_by_actor"] is False
    cursor = page_one.json()["next_cursor"]
    assert cursor is not None

    assert client.post(f"/tweets/{second['id']}/like").status_code == 200

    page_two = client.get(f"/tweets?page_size=1&cursor={cursor}")
    assert page_two.status_code == 200
    assert page_two.json()["items"][0]["id"] == first["id"]
    assert page_two.json()["items"][0]["like_count"] == 1
    assert page_two.json()["items"][0]["liked_by_actor"] is True
    assert page_two.json()["next_cursor"] is None

    client.cookies.clear()
    _register_and_login(client, "other_viewer")
    other_feed = client.get("/tweets?page_size=50").json()["items"]
    by_id = {item["id"]: item for item in other_feed}
    assert by_id[first["id"]]["like_count"] == 1
    assert by_id[first["id"]]["liked_by_actor"] is False
    assert by_id[second["id"]]["like_count"] == 1
    assert by_id[second["id"]]["liked_by_actor"] is False
    assert all(
        set(item) == {"id", "text", "created_at", "author", "like_count", "liked_by_actor"}
        for item in other_feed
    )


def test_omitted_and_explicit_all_are_equivalent_and_emit_scope_bound_v2(client: TestClient) -> None:
    _register_and_login(client)
    for index in range(2):
        assert client.post("/tweets", json={"text": f"global-{index}"}).status_code == 201

    omitted = client.get("/tweets?page_size=1")
    explicit = client.get("/tweets?feed=all&page_size=1")

    assert omitted.status_code == explicit.status_code == 200
    assert omitted.json() == explicit.json()
    cursor = omitted.json()["next_cursor"]
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    assert list(payload) == ["v", "feed", "created_at", "id"]
    assert payload["v"] == 2
    assert payload["feed"] == "all"


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("feed=", "feed"), ("feed=ALL", "feed"), ("feed=%20all", "feed"),
        ("feed=unknown", "feed"), ("feed=mine", "feed"),
        ("feed=all&feed=all", "feed"), ("username=alice", "username"),
        ("feed=all&username=alice", "username"),
        ("feed=following&username=alice", "username"),
        ("feed=profile", "username"),
        ("feed=profile&username=alice&username=bob", "username"),
    ],
)
def test_feed_scope_parser_rejects_invalid_or_ambiguous_input_before_tweet_io(
    client: TestClient, query: str, field: str
) -> None:
    _register_and_login(client)
    statements: list[str] = []
    app_engine = get_engine()
    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(app_engine, "before_cursor_execute", record)
    try:
        response = client.get(f"/tweets?{query}")
    finally:
        event.remove(app_engine, "before_cursor_execute", record)
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "validation_error", "fields": {field: "invalid"}}}
    assert not any("FROM tweets" in " ".join(statement.split()) for statement in statements)


def test_live_scoped_feeds_use_http_membership_exact_projections_and_bounded_queries(
    client: TestClient,
    runtime,
) -> None:
    actor_id = _register_and_login(client, "feed_actor")
    actor_tweet = client.post("/tweets", json={"text": "actor tweet"}).json()

    client.cookies.clear()
    followed_id = _register_and_login(client, "followed_user")
    followed_tweets = [
        client.post("/tweets", json={"text": f"followed-{index}"}).json()
        for index in range(2)
    ]

    client.cookies.clear()
    unrelated_id = _register_and_login(client, "case_check")
    unrelated_tweet = client.post("/tweets", json={"text": "unrelated tweet"}).json()

    client.cookies.clear()
    assert client.post(
        "/auth/login",
        json={"email": "feed_actor@example.com", "password": PASSWORD},
    ).status_code == 204
    assert client.post("/users/followed_user/follow").json() == {
        "username": "followed_user",
        "following": True,
    }

    statements: list[str] = []
    app_engine = get_engine()

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.split()))

    event.listen(app_engine, "before_cursor_execute", record)
    try:
        first_page = client.get("/tweets?feed=following&page_size=1")
    finally:
        event.remove(app_engine, "before_cursor_execute", record)

    assert first_page.status_code == 200
    first_body = first_page.json()
    assert set(first_body) == {"items", "next_cursor"}
    assert len(first_body["items"]) == 1
    assert first_body["next_cursor"] is not None
    assert first_body["items"][0]["author"] == {
        "id": str(followed_id),
        "username": "followed_user",
        "display_name": "Followed User",
    }
    assert set(first_body["items"][0]) == {
        "id",
        "text",
        "created_at",
        "author",
        "like_count",
        "liked_by_actor",
    }
    assert sum("FROM follow_relationships" in statement for statement in statements) == 1
    assert sum("FROM tweets JOIN users" in statement for statement in statements) == 1

    second_page = client.get(
        "/tweets?feed=following&page_size=1&cursor=" + first_body["next_cursor"]
    )
    assert second_page.status_code == 200
    following_ids = {
        first_body["items"][0]["id"], second_page.json()["items"][0]["id"]
    }
    assert following_ids == {tweet["id"] for tweet in followed_tweets}
    assert second_page.json()["next_cursor"] is None
    assert actor_tweet["id"] not in following_ids
    assert unrelated_tweet["id"] not in following_ids

    self_profile = client.get("/tweets?feed=profile&username=feed_actor")
    statements.clear()
    event.listen(app_engine, "before_cursor_execute", record)
    try:
        other_profile = client.get("/tweets?feed=profile&username=%20CASE_CHECK%20")
    finally:
        event.remove(app_engine, "before_cursor_execute", record)
    assert sum("FROM users WHERE users.username =" in statement for statement in statements) == 1
    assert sum("FROM tweets JOIN users" in statement for statement in statements) == 1
    assert [item["id"] for item in self_profile.json()["items"]] == [actor_tweet["id"]]
    assert [item["id"] for item in other_profile.json()["items"]] == [unrelated_tweet["id"]]
    assert self_profile.json()["items"][0]["author"]["id"] == str(actor_id)
    assert other_profile.json()["items"][0]["author"]["id"] == str(unrelated_id)

    cursor = first_body["next_cursor"]
    for path in (
        f"/tweets?cursor={cursor}",
        f"/tweets?feed=profile&username=followed_user&cursor={cursor}",
    ):
        rejected = client.get(path)
        assert rejected.status_code == 422
        assert rejected.json() == {
            "error": {"code": "validation_error", "fields": {"cursor": "invalid"}}
        }


def test_feed_cursor_survives_deleted_boundary_newer_insert_and_page_size_change(client: TestClient, runtime) -> None:
    _register_and_login(client)
    ids = [client.post("/tweets", json={"text": f"tweet-{index}"}).json()["id"] for index in range(5)]
    base = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    with Session(runtime) as session:
        rows = session.execute(select(TweetModel)).scalars().all()
        by_id = {str(row.public_id): row for row in rows}
        for index, public_id in enumerate(ids):
            by_id[public_id].created_at = base + timedelta(minutes=index)
            by_id[public_id].updated_at = base + timedelta(minutes=index)
        session.commit()

    page_one = client.get("/tweets?page_size=2").json()
    boundary_id = page_one["items"][-1]["id"]
    with Session(runtime) as session:
        boundary = session.execute(select(TweetModel).where(TweetModel.public_id == UUID(boundary_id))).scalar_one()
        boundary.deleted_at = boundary.updated_at = base + timedelta(hours=1)
        session.commit()
    newer = client.post("/tweets", json={"text": "newer"}).json()["id"]
    with Session(runtime) as session:
        row = session.execute(select(TweetModel).where(TweetModel.public_id == UUID(newer))).scalar_one()
        row.created_at = row.updated_at = base + timedelta(hours=2)
        session.commit()

    page_two = client.get(f"/tweets?page_size=3&cursor={page_one['next_cursor']}").json()
    assert [item["id"] for item in page_two["items"]] == [ids[2], ids[1], ids[0]]
    assert page_two["next_cursor"] is None
    assert newer not in {item["id"] for item in page_two["items"]}
    assert not ({item["id"] for item in page_one["items"]} & {item["id"] for item in page_two["items"]})


@pytest.mark.parametrize("query", ["page_size=0", "page_size=51", "page_size=", "page_size=1.5", "page_size=true", "page_size=2&page_size=3", "cursor=", "cursor=bad%"])
def test_feed_rejects_invalid_queries(client: TestClient, runtime, query: str) -> None:
    _register_and_login(client)
    response = client.get(f"/tweets?{query}")
    assert response.status_code == 422
    field = "cursor" if query.startswith("cursor") else "page_size"
    assert response.json() == {"error": {"code": "validation_error", "fields": {field: "invalid"}}}
    with Session(runtime) as session:
        assert session.execute(select(TweetModel)).scalars().all() == []


def test_feed_preserves_unauthenticated_envelope(client: TestClient) -> None:
    response = client.get("/tweets")
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthenticated"}}


def test_delete_lifecycle_owner_non_owner_repeat_retained_row_and_feed(client: TestClient, runtime) -> None:
    owner_id = _register_and_login(client, "delete_owner")
    created = client.post("/tweets", json={"text": "delete me"})
    tweet_id = created.json()["id"]
    with Session(runtime) as session:
        before = session.execute(select(TweetModel).where(TweetModel.public_id == UUID(tweet_id))).scalar_one()
        original_updated_at = before.updated_at

    client.cookies.clear()
    _register_and_login(client, "delete_intruder")
    denied = client.delete(f"/tweets/{tweet_id}")
    assert denied.status_code == 403
    assert denied.json() == {"error": {"code": "forbidden"}}
    assert tweet_id in {item["id"] for item in client.get("/tweets").json()["items"]}
    with Session(runtime) as session:
        denied_row = session.execute(select(TweetModel).where(TweetModel.public_id == UUID(tweet_id))).scalar_one()
        assert denied_row.deleted_at is None
        assert denied_row.updated_at == original_updated_at

    client.cookies.clear()
    login = client.post("/auth/login", json={"email": "delete_owner@example.com", "password": PASSWORD})
    assert login.status_code == 204
    deleted = client.delete(f"/tweets/{tweet_id}")
    repeated = client.delete(f"/tweets/{tweet_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert repeated.status_code == 404
    assert repeated.json() == {"error": {"code": "not_found"}}
    assert tweet_id not in {item["id"] for item in client.get("/tweets?page_size=1").json()["items"]}
    with Session(runtime) as session:
        row = session.execute(select(TweetModel).where(TweetModel.public_id == UUID(tweet_id))).scalar_one()
        assert row.author_public_id == owner_id
        assert row.deleted_at is not None
        assert row.deleted_at.tzinfo is not None
        assert row.updated_at == row.deleted_at
        assert row.updated_at > original_updated_at


def test_delete_validation_auth_unknown_and_concurrent_owner_attempts(client: TestClient, runtime) -> None:
    unauthenticated = client.delete("/tweets/not-a-uuid")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json() == {"error": {"code": "unauthenticated"}}

    _register_and_login(client, "concur_owner")
    for invalid in ("not-a-uuid", "22222222-2222-1222-8222-222222222222", "abcdefab-cdef-4abc-8def-abcdefabcdef".upper()):
        response = client.delete(f"/tweets/{invalid}")
        assert response.status_code == 422
        assert response.json() == {"error": {"code": "validation_error", "fields": {"tweet_id": "invalid"}}}
    unknown = client.delete("/tweets/33333333-3333-4333-8333-333333333333")
    assert unknown.status_code == 404
    assert unknown.json() == {"error": {"code": "not_found"}}

    tweet_id = client.post("/tweets", json={"text": "one transition"}).json()["id"]
    cookie = client.cookies.get("flock_session")

    def attempt_delete() -> tuple[int, bytes]:
        with TestClient(app, raise_server_exceptions=False) as concurrent_client:
            concurrent_client.cookies.set("flock_session", cookie)
            response = concurrent_client.delete(f"/tweets/{tweet_id}")
            return response.status_code, response.content

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt_delete(), range(2)))
    assert sorted(status_code for status_code, _ in results) == [204, 404]
    assert next(body for status_code, body in results if status_code == 204) == b""
    assert client.delete(f"/tweets/{tweet_id}").status_code == 404
    with Session(runtime) as session:
        row = session.execute(select(TweetModel).where(TweetModel.public_id == UUID(tweet_id))).scalar_one()
        assert row.deleted_at is not None
        assert row.updated_at == row.deleted_at
