"""Live PostgreSQL contract for tweet-like schema and migration."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, delete, func, inspect, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip("TEST_DATABASE_URL is not set", allow_module_level=True)
if make_url(TEST_DATABASE_URL).get_backend_name() != "postgresql":
    raise RuntimeError("TEST_DATABASE_URL must use PostgreSQL")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.auth.infrastructure.session_model import SessionModel  # noqa: E402
from app.tweets.infrastructure.tweet_like_model import TweetLikeModel  # noqa: E402
from app.tweets.infrastructure.tweet_model import TweetModel  # noqa: E402
from app.users.infrastructure.follow_relationship_model import (  # noqa: E402
    FollowRelationshipModel,
)
from app.users.infrastructure.user_model import UserModel  # noqa: E402

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def _config() -> AlembicConfig:
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


def _clear(engine) -> None:
    with Session(engine) as session:
        session.execute(delete(TweetLikeModel))
        session.execute(delete(FollowRelationshipModel))
        session.execute(delete(TweetModel))
        session.execute(delete(SessionModel))
        session.execute(delete(UserModel))
        session.commit()


@pytest.fixture(scope="module", autouse=True)
def head_database():
    alembic_command.upgrade(_config(), "head")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        yield engine
    finally:
        alembic_command.upgrade(_config(), "head")
        _clear(engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_rows(head_database):
    _clear(head_database)
    yield
    alembic_command.upgrade(_config(), "head")
    _clear(head_database)


def _user(session: Session, username: str) -> UUID:
    public_id = uuid4()
    session.add(UserModel(
        public_id=public_id, email=f"{username}@example.com", username=username,
        display_name=username.title(), password_hash="hash", created_at=NOW, updated_at=NOW,
    ))
    session.commit()
    return public_id


def _tweet(session: Session, author: UUID, *, deleted=False) -> UUID:
    public_id = uuid4()
    session.add(TweetModel(
        public_id=public_id, author_public_id=author, text="schema test",
        created_at=NOW, updated_at=NOW, deleted_at=NOW if deleted else None,
    ))
    session.commit()
    return public_id


def test_tweet_likes_has_exact_registered_schema(head_database) -> None:
    table = TweetLikeModel.__table__
    assert list(table.c.keys()) == ["tweet_public_id", "actor_public_id"]
    assert all(not column.nullable for column in table.c)
    assert all(column.type.__class__.__name__ == "UUID" for column in table.c)

    schema = inspect(head_database)
    live_columns = schema.get_columns("tweet_likes")
    assert [column["name"] for column in live_columns] == [
        "tweet_public_id", "actor_public_id",
    ]
    assert all(column["nullable"] is False for column in live_columns)
    assert all(column["type"].__class__.__name__ == "UUID" for column in live_columns)
    primary_key = schema.get_pk_constraint("tweet_likes")
    assert primary_key["name"] == "pk_tweet_likes"
    assert primary_key["constrained_columns"] == ["tweet_public_id", "actor_public_id"]
    foreign_keys = {item["name"]: item for item in schema.get_foreign_keys("tweet_likes")}
    assert set(foreign_keys) == {
        "fk_tweet_likes_tweet_public_id_tweets",
        "fk_tweet_likes_actor_public_id_users",
    }
    expected_foreign_keys = {
        "fk_tweet_likes_tweet_public_id_tweets":
            (["tweet_public_id"], "tweets", ["public_id"]),
        "fk_tweet_likes_actor_public_id_users":
            (["actor_public_id"], "users", ["public_id"]),
    }
    for name, (columns, table_name, referred_columns) in expected_foreign_keys.items():
        assert foreign_keys[name]["constrained_columns"] == columns
        assert foreign_keys[name]["referred_table"] == table_name
        assert foreign_keys[name]["referred_columns"] == referred_columns
        assert foreign_keys[name]["options"].get("ondelete") == "RESTRICT"
    indexes = {item["name"]: item for item in schema.get_indexes("tweet_likes")}
    actor_index = indexes["ix_tweet_likes_actor_public_id_tweet_public_id"]
    assert actor_index["column_names"] == ["actor_public_id", "tweet_public_id"]
    assert actor_index["unique"] is False
    assert "app.tweets.infrastructure.tweet_like_model" in Path("alembic/env.py").read_text()


def test_database_accepts_self_like_and_rejects_duplicates_and_orphans(head_database) -> None:
    with Session(head_database) as session:
        author = _user(session, "selflike")
        tweet = _tweet(session, author)
        session.add(TweetLikeModel(tweet_public_id=tweet, actor_public_id=author))
        session.commit()

        cases = [
            ("pk_tweet_likes", tweet, author),
            ("fk_tweet_likes_tweet_public_id_tweets", uuid4(), author),
            ("fk_tweet_likes_actor_public_id_users", tweet, uuid4()),
        ]
        for constraint, tweet_id, actor_id in cases:
            with pytest.raises(IntegrityError) as caught:
                with session.begin():
                    session.add(TweetLikeModel(
                        tweet_public_id=tweet_id, actor_public_id=actor_id
                    ))
                    session.flush()
            assert caught.value.orig.diag.constraint_name == constraint
        assert session.scalar(select(func.count()).select_from(TweetLikeModel)) == 1
    _clear(head_database)


def test_soft_delete_retains_like_and_hard_deletes_are_restrictive(head_database) -> None:
    with Session(head_database) as session:
        author = _user(session, "retained")
        actor = _user(session, "liker")
        tweet = _tweet(session, author)
        session.add(TweetLikeModel(tweet_public_id=tweet, actor_public_id=actor))
        session.commit()
        session.execute(update(TweetModel).where(TweetModel.public_id == tweet).values(deleted_at=NOW))
        session.commit()
        assert session.scalar(select(func.count()).select_from(TweetLikeModel)) == 1
        session.rollback()
        for model, public_id, constraint in (
            (TweetModel, tweet, "fk_tweet_likes_tweet_public_id_tweets"),
            (UserModel, actor, "fk_tweet_likes_actor_public_id_users"),
        ):
            with pytest.raises(IntegrityError) as caught:
                with session.begin():
                    session.execute(delete(model).where(model.public_id == public_id))
            assert caught.value.orig.diag.constraint_name == constraint
    _clear(head_database)


def test_representative_data_survives_empty_like_table_up_down_up(head_database) -> None:
    config = _config()
    with Session(head_database) as session:
        actor = _user(session, "migrationa")
        target = _user(session, "migrationb")
        tweet = _tweet(session, actor, deleted=True)
        session.add(SessionModel(
            token_hash=b"x" * 32, user_public_id=actor, issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        ))
        session.add(FollowRelationshipModel(
            follower_public_id=actor, followed_public_id=target, created_at=NOW,
        ))
        session.commit()
        assert session.scalar(select(func.count()).select_from(TweetLikeModel)) == 0

    alembic_command.downgrade(config, "a6b7c8d9e0f1")
    try:
        assert "tweet_likes" not in inspect(head_database).get_table_names()
        with Session(head_database) as session:
            assert session.scalar(select(func.count()).select_from(UserModel)) == 2
            assert session.scalar(select(func.count()).select_from(SessionModel)) == 1
            assert session.scalar(select(func.count()).select_from(TweetModel)) == 1
            assert session.scalar(select(func.count()).select_from(FollowRelationshipModel)) == 1
            assert session.scalar(select(TweetModel.deleted_at).where(TweetModel.public_id == tweet)) == NOW
    finally:
        alembic_command.upgrade(config, "head")
    assert "tweet_likes" in inspect(head_database).get_table_names()
    with Session(head_database) as session:
        assert session.scalar(select(func.count()).select_from(TweetLikeModel)) == 0
    _clear(head_database)


def test_failed_upgrade_is_atomic_and_does_not_advance_revision(head_database) -> None:
    config = _config()
    alembic_command.downgrade(config, "a6b7c8d9e0f1")
    try:
        with head_database.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE tweet_likes (placeholder integer)")
        with pytest.raises(ProgrammingError):
            alembic_command.upgrade(config, "head")
        with head_database.connect() as connection:
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "a6b7c8d9e0f1"
            connection.exec_driver_sql("DROP TABLE tweet_likes")
            connection.commit()
    finally:
        alembic_command.upgrade(config, "head")
