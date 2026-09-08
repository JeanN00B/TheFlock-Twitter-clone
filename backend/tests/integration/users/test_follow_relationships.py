"""Live PostgreSQL evidence for follow persistence and migration."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, delete, func, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip("TEST_DATABASE_URL is not set; PostgreSQL follow integration test skipped", allow_module_level=True)

try:
    _database_url = make_url(TEST_DATABASE_URL)
except (ArgumentError, TypeError, ValueError):
    raise RuntimeError("TEST_DATABASE_URL must be a valid PostgreSQL URL") from None
if _database_url.get_backend_name() != "postgresql":
    raise RuntimeError("TEST_DATABASE_URL must use a PostgreSQL URL")

from app.auth.infrastructure.session_model import SessionModel  # noqa: E402
from app.tweets.infrastructure.tweet_model import TweetModel  # noqa: E402
from app.users.application.follow_relationships import FollowState  # noqa: E402
from app.users.domain.user import NewUser  # noqa: E402
from app.users.infrastructure.follow_relationship_model import FollowRelationshipModel  # noqa: E402
from app.users.infrastructure.follow_relationship_repository import SQLAlchemyFollowRelationshipRepository  # noqa: E402
from app.users.infrastructure.user_model import UserModel  # noqa: E402
from app.users.infrastructure.user_repository import SQLAlchemyUserRepository  # noqa: E402

INSTANT = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$somesalt$hash"


def config() -> AlembicConfig:
    value = AlembicConfig("alembic.ini")
    value.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return value


def clear(engine) -> None:
    with Session(engine) as session:
        session.execute(delete(FollowRelationshipModel))
        session.execute(delete(TweetModel))
        session.execute(delete(SessionModel))
        session.execute(delete(UserModel))
        session.commit()


@pytest.fixture(scope="module", autouse=True)
def migrated():
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    alembic_command.upgrade(config(), "e4f5a6b7c8d9")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture()
def engine():
    value = create_engine(TEST_DATABASE_URL)
    clear(value)
    try:
        yield value
    finally:
        clear(value)
        value.dispose()


def add_user(session: Session, username: str):
    user = NewUser(uuid4(), f"{username}@example.com", username, username.title(), PASSWORD_HASH, INSTANT, INSTANT)
    SQLAlchemyUserRepository(session).add(user)
    return user


def test_schema_has_exact_named_protections(engine) -> None:
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("follow_relationships")}
    assert set(columns) == {"id", "follower_public_id", "followed_public_id", "created_at"}
    assert columns["id"]["type"].__class__.__name__ == "BIGINT"
    assert columns["created_at"]["type"].timezone is True
    assert inspector.get_pk_constraint("follow_relationships")["name"] == "pk_follow_relationships_id"
    assert {item["name"] for item in inspector.get_unique_constraints("follow_relationships")} == {"uq_follow_relationships_follower_followed"}
    assert {item["name"] for item in inspector.get_check_constraints("follow_relationships")} == {"ck_follow_relationships_not_self"}
    foreign_keys = {item["name"]: item for item in inspector.get_foreign_keys("follow_relationships")}
    assert set(foreign_keys) == {"fk_follow_relationships_follower_users", "fk_follow_relationships_followed_users"}
    assert all(item["options"].get("ondelete") == "RESTRICT" for item in foreign_keys.values())
    indexes = {item["name"]: item for item in inspector.get_indexes("follow_relationships")}
    assert indexes["ix_follow_relationships_followed_follower"]["column_names"] == ["followed_public_id", "follower_public_id"]
    assert indexes["ix_follow_relationships_followed_follower"]["unique"] is False


def test_follow_is_idempotent_preserves_timestamp_and_unfollow_deletes(engine) -> None:
    with Session(engine) as session:
        actor = add_user(session, "alice_42")
        target = add_user(session, "bob_42")
        repository = SQLAlchemyFollowRelationshipRepository(session)
        assert repository.set_state(actor.public_id, "bob_42", True, INSTANT) == FollowState("bob_42", True)
        later = datetime(2026, 9, 7, 13, 0, tzinfo=timezone.utc)
        assert repository.set_state(actor.public_id, "bob_42", True, later) == FollowState("bob_42", True)
        row = session.execute(select(FollowRelationshipModel)).scalar_one()
        assert row.created_at == INSTANT
        session.rollback()
        assert repository.set_state(actor.public_id, "bob_42", False, later) == FollowState("bob_42", False)
        assert session.execute(select(func.count()).select_from(FollowRelationshipModel)).scalar_one() == 0
        session.rollback()
        assert repository.set_state(actor.public_id, "bob_42", False, later) == FollowState("bob_42", False)
        assert target.public_id != actor.public_id
        assert not session.in_transaction()


def test_unknown_target_returns_none_without_leaving_transaction(engine) -> None:
    with Session(engine) as session:
        actor = add_user(session, "alice_42")
        result = SQLAlchemyFollowRelationshipRepository(session).set_state(actor.public_id, "nobody", True, INSTANT)
        assert result is None
        assert not session.in_transaction()


def test_both_named_foreign_keys_restrict_user_deletion(engine) -> None:
    with Session(engine) as session:
        actor = add_user(session, "alice_42")
        target = add_user(session, "bob_42")
        SQLAlchemyFollowRelationshipRepository(session).set_state(actor.public_id, "bob_42", True, INSTANT)
    for endpoint in (actor.public_id, target.public_id):
        with Session(engine) as session:
            with pytest.raises(IntegrityError) as raised:
                with session.begin():
                    session.execute(delete(UserModel).where(UserModel.public_id == endpoint))
            assert raised.value.orig.diag.constraint_name in {"fk_follow_relationships_follower_users", "fk_follow_relationships_followed_users"}


def test_concurrent_same_verb_requests_converge(engine) -> None:
    with Session(engine) as session:
        actor = add_user(session, "alice_42")
        add_user(session, "bob_42")

    def set_state(following: bool):
        with Session(engine) as session:
            return SQLAlchemyFollowRelationshipRepository(session).set_state(
                actor.public_id, "bob_42", following, INSTANT
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(set_state, (True, True)))
    assert results == [FollowState("bob_42", True), FollowState("bob_42", True)]
    with Session(engine) as session:
        assert session.execute(select(func.count()).select_from(FollowRelationshipModel)).scalar_one() == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(set_state, (False, False)))
    assert results == [FollowState("bob_42", False), FollowState("bob_42", False)]
    with Session(engine) as session:
        assert session.execute(select(func.count()).select_from(FollowRelationshipModel)).scalar_one() == 0


def test_migration_downgrade_reupgrade_preserves_archived_objects(engine) -> None:
    with Session(engine) as session:
        actor = add_user(session, "migration_user")

    alembic_command.downgrade(config(), "d3e4f5a6b7c8")
    try:
        inspector = inspect(engine)
        assert "follow_relationships" not in inspector.get_table_names()
        assert {"users", "sessions", "tweets"} <= set(inspector.get_table_names())
        indexes = {item["name"] for item in inspector.get_indexes("tweets")}
        assert "ix_tweets_active_timeline_created_at_public_id_desc" in indexes
    finally:
        alembic_command.upgrade(config(), "e4f5a6b7c8d9")

    with Session(engine) as session:
        assert session.execute(
            select(func.count()).select_from(UserModel).where(
                UserModel.public_id == actor.public_id
            )
        ).scalar_one() == 1
        assert "follow_relationships" in inspect(engine).get_table_names()
