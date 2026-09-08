"""Live PostgreSQL contract for tweet persistence and repository behavior."""

import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; live PostgreSQL tweet repository tests skipped",
        allow_module_level=True,
    )

from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import ArgumentError  # noqa: E402

try:
    _database_url = make_url(TEST_DATABASE_URL)
except (ArgumentError, TypeError, ValueError):
    raise RuntimeError("TEST_DATABASE_URL must be a valid PostgreSQL URL") from None
if _database_url.get_backend_name() != "postgresql":
    raise RuntimeError("TEST_DATABASE_URL must use a PostgreSQL URL")

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from alembic import command as alembic_command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from sqlalchemy import create_engine, delete, event, inspect, select, text  # noqa: E402
from sqlalchemy.exc import DataError, IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.auth.infrastructure.session_model import SessionModel  # noqa: E402
from app.tweets.application.ports import DeleteOutcome, FeedCursor  # noqa: E402
from app.tweets.domain.tweet import Tweet  # noqa: E402
from app.tweets.infrastructure.tweet_model import TweetModel  # noqa: E402
from app.tweets.infrastructure.tweet_repository import SQLAlchemyTweetRepository  # noqa: E402
from app.users.infrastructure.user_model import UserModel  # noqa: E402

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$salt$hash"


def _alembic_config() -> AlembicConfig:
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    alembic_command.upgrade(_alembic_config(), "head")
    yield
    alembic_command.upgrade(_alembic_config(), "head")


@pytest.fixture()
def engine():
    value = create_engine(TEST_DATABASE_URL)
    yield value
    value.dispose()


def _clean(session: Session) -> None:
    session.execute(delete(TweetModel))
    session.execute(delete(SessionModel))
    session.execute(delete(UserModel))
    session.commit()


@pytest.fixture()
def db_session(engine):
    session = Session(engine)
    _clean(session)
    yield session
    session.rollback()
    _clean(session)
    session.close()


def _user(session: Session, *, public_id: UUID | None = None, username: str = "alice") -> UUID:
    public_id = public_id or uuid4()
    session.add(
        UserModel(
            public_id=public_id,
            email=f"{username}@example.com",
            username=username,
            display_name=username.title(),
            password_hash=PASSWORD_HASH,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.commit()
    return public_id


def _tweet(author_id: UUID, *, public_id: UUID | None = None, text_value: str = "hello", created_at=NOW) -> Tweet:
    return Tweet.create(
        id=public_id or uuid4(), author_id=author_id, text=text_value, created_at=created_at
    )


def test_model_and_live_schema_have_exact_contract(engine) -> None:
    table = TweetModel.__table__
    assert table.c.id.primary_key and table.c.id.identity is not None
    assert table.c.id.type.__class__.__name__ == "BigInteger"
    assert table.c.public_id.type.__class__.__name__ == "UUID"
    assert table.c.author_public_id.type.__class__.__name__ == "UUID"
    assert table.c.text.type.length == 280
    assert table.c.created_at.type.timezone is True
    assert table.c.updated_at.type.timezone is True
    assert table.c.deleted_at.type.timezone is True
    assert table.c.deleted_at.nullable is True
    assert all(not table.c[name].nullable for name in (
        "id", "public_id", "author_public_id", "text", "created_at", "updated_at"
    ))

    inspector = inspect(engine)
    assert "tweets" in inspector.get_table_names()
    constraints = {
        item["name"] for group in (
            inspector.get_pk_constraint("tweets"),
            *inspector.get_unique_constraints("tweets"),
            *inspector.get_foreign_keys("tweets"),
            *inspector.get_check_constraints("tweets"),
        ) for item in ([group] if isinstance(group, dict) else group)
    }
    assert {
        "pk_tweets_id", "uq_tweets_public_id",
        "fk_tweets_author_public_id_users", "ck_tweets_text_nonempty",
        "ck_tweets_text_max_280", "ck_tweets_timestamp_order",
    } <= constraints
    indexes = {item["name"]: item for item in inspector.get_indexes("tweets")}
    index = indexes["ix_tweets_active_timeline_created_at_public_id_desc"]
    assert index["column_names"] == ["created_at", "public_id"]
    definition = index["dialect_options"]["postgresql_where"]
    assert "deleted_at IS NULL" in str(definition)
    with engine.connect() as connection:
        sql = connection.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE tablename='tweets' AND indexname="
            "'ix_tweets_active_timeline_created_at_public_id_desc'"
        )).scalar_one()
    assert "created_at DESC" in sql and "public_id DESC" in sql


def test_migration_source_and_registration_are_exact() -> None:
    source = Path("alembic/versions/d3e4f5a6b7c8_create_tweets.py").read_text()
    assert 'down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"' in source
    for name in (
        "pk_tweets_id", "uq_tweets_public_id", "fk_tweets_author_public_id_users",
        "ck_tweets_text_nonempty", "ck_tweets_text_max_280",
        "ck_tweets_timestamp_order", "ix_tweets_active_timeline_created_at_public_id_desc",
    ):
        assert name in source
    assert 'ondelete="RESTRICT"' in source
    assert "app.tweets.infrastructure.tweet_model" in Path("alembic/env.py").read_text()


def test_named_database_protections_reject_invalid_rows(db_session: Session) -> None:
    author = _user(db_session)
    repository = SQLAlchemyTweetRepository(db_session)
    original = _tweet(author)
    repository.add(original)

    cases = [
        ("uq_tweets_public_id", dict(public_id=original.id, author_public_id=author, text="other", created_at=NOW, updated_at=NOW)),
        ("fk_tweets_author_public_id_users", dict(public_id=uuid4(), author_public_id=uuid4(), text="orphan", created_at=NOW, updated_at=NOW)),
        ("ck_tweets_text_nonempty", dict(public_id=uuid4(), author_public_id=author, text="", created_at=NOW, updated_at=NOW)),
        (None, dict(public_id=uuid4(), author_public_id=author, text="x" * 281, created_at=NOW, updated_at=NOW)),
        ("ck_tweets_timestamp_order", dict(public_id=uuid4(), author_public_id=author, text="bad time", created_at=NOW, updated_at=NOW - timedelta(seconds=1))),
    ]
    for expected, values in cases:
        with pytest.raises((IntegrityError, DataError)) as caught:
            with db_session.begin():
                db_session.add(TweetModel(**values, deleted_at=None))
                db_session.flush()
        if expected is not None:
            assert caught.value.orig.diag.constraint_name == expected
    assert len(db_session.execute(select(TweetModel)).scalars().all()) == 1


def test_author_foreign_key_is_restrictive(db_session: Session) -> None:
    author = _user(db_session)
    SQLAlchemyTweetRepository(db_session).add(_tweet(author))
    with pytest.raises(IntegrityError) as caught:
        with db_session.begin():
            db_session.execute(delete(UserModel).where(UserModel.public_id == author))
    assert caught.value.orig.diag.constraint_name == "fk_tweets_author_public_id_users"
    assert db_session.execute(select(TweetModel)).scalar_one().author_public_id == author


def test_add_commits_and_failure_rolls_back_for_session_reuse(db_session: Session) -> None:
    author = _user(db_session)
    repository = SQLAlchemyTweetRepository(db_session)
    first = _tweet(author)
    repository.add(first)
    with Session(db_session.bind) as independent:
        assert independent.execute(select(TweetModel.public_id)).scalar_one() == first.id

    with pytest.raises(IntegrityError):
        repository.add(_tweet(author, public_id=first.id, text_value="duplicate"))
    second = _tweet(author, text_value="after rollback")
    repository.add(second)
    assert set(db_session.execute(select(TweetModel.public_id)).scalars()) == {first.id, second.id}


def test_list_active_is_joined_private_free_ordered_and_boundary_safe(db_session: Session) -> None:
    first_author = _user(db_session, username="alice")
    second_author = _user(db_session, username="bob")
    lower = UUID("11111111-1111-4111-8111-111111111111")
    upper = UUID("ffffffff-ffff-4fff-bfff-ffffffffffff")
    older = UUID("22222222-2222-4222-8222-222222222222")
    repository = SQLAlchemyTweetRepository(db_session)
    repository.add(_tweet(first_author, public_id=lower, text_value="lower tie"))
    repository.add(_tweet(second_author, public_id=upper, text_value="upper tie"))
    repository.add(_tweet(first_author, public_id=older, text_value="older", created_at=NOW - timedelta(seconds=1)))

    statements: list[str] = []
    def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        items = repository.list_active(None, 10)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)
    assert [item.id for item in items] == [upper, lower, older]
    assert len(statements) == 1
    assert {item.author.username for item in items} == {"alice", "bob"}
    assert all(set(vars(item.author)) == {"id", "username", "display_name"} for item in items)

    outcome = repository.soft_delete(lower, first_author, NOW + timedelta(seconds=1))
    assert outcome is DeleteOutcome.DELETED
    assert [item.id for item in repository.list_active(FeedCursor(NOW, lower), 10)] == [older]
    retained = db_session.execute(select(TweetModel).where(TweetModel.public_id == lower)).scalar_one()
    assert retained.deleted_at == NOW + timedelta(seconds=1)


def test_soft_delete_classifies_and_rolls_back(db_session: Session, monkeypatch) -> None:
    owner = _user(db_session, username="owner")
    other = _user(db_session, username="other")
    repository = SQLAlchemyTweetRepository(db_session)
    tweet = _tweet(owner)
    repository.add(tweet)
    assert repository.soft_delete(uuid4(), owner, NOW + timedelta(seconds=1)) is DeleteOutcome.NOT_FOUND
    assert repository.soft_delete(tweet.id, other, NOW + timedelta(seconds=1)) is DeleteOutcome.FORBIDDEN

    original_flush = db_session.flush
    monkeypatch.setattr(db_session, "flush", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("flush failed")))
    with pytest.raises(RuntimeError, match="flush failed"):
        repository.soft_delete(tweet.id, owner, NOW + timedelta(seconds=1))
    monkeypatch.setattr(db_session, "flush", original_flush)
    assert db_session.execute(select(TweetModel.deleted_at).where(TweetModel.public_id == tweet.id)).scalar_one() is None
    db_session.rollback()
    assert repository.soft_delete(tweet.id, owner, NOW + timedelta(seconds=2)) is DeleteOutcome.DELETED
    assert repository.soft_delete(tweet.id, owner, NOW + timedelta(seconds=3)) is DeleteOutcome.NOT_FOUND


def test_concurrent_independent_session_delete_has_one_success(engine) -> None:
    with Session(engine) as setup:
        _clean(setup)
        owner = _user(setup)
        tweet = _tweet(owner)
        SQLAlchemyTweetRepository(setup).add(tweet)
    barrier = threading.Barrier(2)
    outcomes: list[DeleteOutcome] = []

    def attempt() -> None:
        with Session(engine) as session:
            barrier.wait(timeout=10)
            outcomes.append(SQLAlchemyTweetRepository(session).soft_delete(
                tweet.id, owner, NOW + timedelta(seconds=1)
            ))

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(outcome.value for outcome in outcomes) == ["deleted", "not_found"]
    with Session(engine) as verify:
        row = verify.execute(select(TweetModel).where(TweetModel.public_id == tweet.id)).scalar_one()
        assert row.deleted_at == NOW + timedelta(seconds=1)
        _clean(verify)


def test_migration_downgrade_then_upgrade_preserves_existing_auth_schema(engine) -> None:
    with Session(engine) as session:
        _clean(session)
    config = _alembic_config()
    alembic_command.downgrade(config, "c2d3e4f5a6b7")
    try:
        inspector = inspect(engine)
        assert "tweets" not in inspector.get_table_names()
        assert {"users", "sessions"} <= set(inspector.get_table_names())
    finally:
        alembic_command.upgrade(config, "head")
    assert "tweets" in inspect(engine).get_table_names()
