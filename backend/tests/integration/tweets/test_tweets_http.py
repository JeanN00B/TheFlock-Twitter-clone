"""Live PostgreSQL HTTP evidence for authenticated tweet creation."""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select, update
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

EXPECTED_DATABASE_URL = "postgresql+psycopg://flock:flockpw@localhost:5434/flockdb"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; PostgreSQL tweet HTTP integration test skipped",
        allow_module_level=True,
    )
if TEST_DATABASE_URL != EXPECTED_DATABASE_URL:
    raise RuntimeError("tweet HTTP integration requires the exact TEST_DATABASE_URL PostgreSQL URL")

from app.auth.infrastructure.session_model import SessionModel  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.infrastructure.database import get_engine, get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.tweets.infrastructure.tweet_model import TweetModel  # noqa: E402
from app.users.infrastructure.user_model import UserModel  # noqa: E402

PASSWORD = "exact tweet creation password"


def _alembic_config() -> AlembicConfig:
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


def _clear_rows(engine) -> None:
    with Session(engine) as session:
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
    assert set(first.json()) == {"id", "text", "created_at", "author"}
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
    assert all(set(item) == {"id", "text", "created_at", "author"} for item in body["items"])
    assert all(set(item["author"]) == {"id", "username", "display_name"} for item in body["items"])
    assert body["next_cursor"] is None
    assert sum("FROM tweets JOIN users" in " ".join(statement.split()) for statement in statements) == 1


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
