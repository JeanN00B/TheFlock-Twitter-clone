"""WU4 relationship-list migration contract and PostgreSQL round-trip."""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.tweets.infrastructure.tweet_model import TweetModel
from app.users.infrastructure.follow_relationship_model import FollowRelationshipModel

REVISION = "f5a6b7c8d9e0"
WU6_REVISION = "a6b7c8d9e0f1"
AUTHOR_INDEX = "ix_tweets_active_author_timeline_created_at_public_id_desc"
INDEXES = {
    "ix_follow_relationships_followed_created_at_follower_desc",
    "ix_follow_relationships_follower_created_at_followed_desc",
}


def test_wu6_revision_and_model_define_exact_active_author_index() -> None:
    source = Path(
        f"alembic/versions/{WU6_REVISION}_add_active_author_timeline_index.py"
    ).read_text()
    assert 'revision: str = "a6b7c8d9e0f1"' in source
    assert 'down_revision: str | Sequence[str] | None = "f5a6b7c8d9e0"' in source
    assert AUTHOR_INDEX in source
    model_index = next(index for index in TweetModel.__table__.indexes if index.name == AUTHOR_INDEX)
    assert [str(expression) for expression in model_index.expressions] == [
        "tweets.author_public_id", "created_at DESC", "public_id DESC"
    ]
    assert str(model_index.dialect_options["postgresql"]["where"]) == "deleted_at IS NULL"


def test_wu4_revision_and_model_define_only_relationship_list_indexes() -> None:
    source = Path(f"alembic/versions/{REVISION}_add_relationship_list_indexes.py").read_text()
    assert 'revision: str = "f5a6b7c8d9e0"' in source
    assert 'down_revision: str | Sequence[str] | None = "e4f5a6b7c8d9"' in source
    model_indexes = {index.name for index in FollowRelationshipModel.__table__.indexes}
    assert INDEXES < model_indexes
    assert "ix_tweets_active_author_timeline_created_at_public_id_desc" not in source


@pytest.mark.integration
def test_wu6_migration_round_trip_preserves_wu4_and_global_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not set; PostgreSQL migration test skipped")
    if make_url(database_url).get_backend_name() != "postgresql":
        raise RuntimeError("TEST_DATABASE_URL must use a PostgreSQL URL")
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, WU6_REVISION)
    engine = create_engine(database_url)
    try:
        assert AUTHOR_INDEX in {item["name"] for item in inspect(engine).get_indexes("tweets")}
        command.downgrade(config, REVISION)
        tweet_indexes = {item["name"] for item in inspect(engine).get_indexes("tweets")}
        assert AUTHOR_INDEX not in tweet_indexes
        assert "ix_tweets_active_timeline_created_at_public_id_desc" in tweet_indexes
        assert INDEXES <= {item["name"] for item in inspect(engine).get_indexes("follow_relationships")}
    finally:
        command.upgrade(config, WU6_REVISION)
        engine.dispose()


@pytest.mark.integration
def test_wu4_migration_downgrade_and_reupgrade_preserve_relationship_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not set; PostgreSQL migration test skipped")
    if make_url(database_url).get_backend_name() != "postgresql":
        raise RuntimeError("TEST_DATABASE_URL must use a PostgreSQL URL")

    from alembic import command
    from alembic.config import Config
    from app.core.settings import get_settings

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, REVISION)
    engine = create_engine(database_url)
    before = None
    try:
        with engine.begin() as connection:
            before = connection.execute(text("select count(*) from follow_relationships")).scalar_one()
        assert INDEXES <= {item["name"] for item in inspect(engine).get_indexes("follow_relationships")}

        command.downgrade(config, "e4f5a6b7c8d9")
        assert INDEXES.isdisjoint({item["name"] for item in inspect(engine).get_indexes("follow_relationships")})
        with engine.begin() as connection:
            assert connection.execute(text("select count(*) from follow_relationships")).scalar_one() == before
    finally:
        try:
            command.upgrade(config, WU6_REVISION)
            assert INDEXES <= {item["name"] for item in inspect(engine).get_indexes("follow_relationships")}
            if before is not None:
                with engine.begin() as connection:
                    assert connection.execute(text("select count(*) from follow_relationships")).scalar_one() == before
        finally:
            engine.dispose()
