"""Live PostgreSQL contract for the tweet-like repository adapter."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; live PostgreSQL like repository tests skipped",
        allow_module_level=True,
    )

from alembic import command as alembic_command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from sqlalchemy import create_engine, delete, event, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import ArgumentError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

try:
    _database_url = make_url(TEST_DATABASE_URL)
except (ArgumentError, TypeError, ValueError):
    raise RuntimeError("TEST_DATABASE_URL must be a valid PostgreSQL URL") from None
if _database_url.get_backend_name() != "postgresql":
    raise RuntimeError("TEST_DATABASE_URL must use a PostgreSQL URL")

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.auth.infrastructure.session_model import SessionModel  # noqa: E402
from app.tweets.application.ports import DeleteOutcome  # noqa: E402
from app.tweets.domain.tweet import Tweet  # noqa: E402
from app.tweets.infrastructure.tweet_like_model import TweetLikeModel  # noqa: E402
from app.tweets.infrastructure.tweet_model import TweetModel  # noqa: E402
from app.tweets.infrastructure.tweet_repository import SQLAlchemyTweetRepository  # noqa: E402
from app.tweets.infrastructure.tweet_like_repository import (  # noqa: E402
    SQLAlchemyTweetLikeRepository,
)
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
    session.execute(delete(TweetLikeModel))
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


def _user(session: Session, *, username: str = "alice") -> UUID:
    public_id = uuid4()
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


def _tweet(author_id: UUID, *, public_id: UUID | None = None) -> Tweet:
    return Tweet.create(
        id=public_id or uuid4(),
        author_id=author_id,
        text="hello",
        created_at=NOW,
    )


def test_first_and_repeated_present_are_authoritative(db_session: Session) -> None:
    actor_id = _user(db_session)
    tweet = _tweet(actor_id)
    SQLAlchemyTweetRepository(db_session).add(tweet)
    repository = SQLAlchemyTweetLikeRepository(db_session)

    first = repository.set_state(tweet.id, actor_id, True)
    repeated = repository.set_state(tweet.id, actor_id, True)

    assert first is not None
    assert first.tweet_id == tweet.id
    assert first.like_count == 1
    assert first.liked_by_actor is True
    assert repeated == first
    with Session(db_session.bind) as independent:
        rows = independent.execute(select(TweetLikeModel)).scalars().all()
        assert len(rows) == 1
        assert (rows[0].tweet_public_id, rows[0].actor_public_id) == (
            tweet.id,
            actor_id,
        )


def test_first_and_repeated_absent_and_self_like(db_session: Session) -> None:
    actor_id = _user(db_session)
    tweet = _tweet(actor_id)
    SQLAlchemyTweetRepository(db_session).add(tweet)
    repository = SQLAlchemyTweetLikeRepository(db_session)

    first = repository.set_state(tweet.id, actor_id, False)
    repeated = repository.set_state(tweet.id, actor_id, False)
    self_like = repository.set_state(tweet.id, actor_id, True)

    assert first is not None and first.like_count == 0 and not first.liked_by_actor
    assert repeated == first
    assert self_like is not None and self_like.like_count == 1
    assert self_like.liked_by_actor is True


def test_different_actors_have_exact_counts(db_session: Session) -> None:
    author = _user(db_session)
    second = _user(db_session, username="second")
    third = _user(db_session, username="third")
    tweet = _tweet(author)
    SQLAlchemyTweetRepository(db_session).add(tweet)
    repository = SQLAlchemyTweetLikeRepository(db_session)

    first_state = repository.set_state(tweet.id, author, True)
    second_state = repository.set_state(tweet.id, second, True)
    third_state = repository.set_state(tweet.id, third, False)

    assert {first_state.like_count, second_state.like_count} == {1, 2}
    assert first_state.liked_by_actor is True
    assert second_state.liked_by_actor is True
    assert third_state.like_count == 2 and third_state.liked_by_actor is False


def test_unknown_and_deleted_targets_do_no_relationship_sql(
    db_session: Session,
) -> None:
    actor_id = _user(db_session)
    tweet = _tweet(actor_id)
    SQLAlchemyTweetRepository(db_session).add(tweet)
    repository = SQLAlchemyTweetLikeRepository(db_session)
    assert repository.set_state(tweet.id, actor_id, True) is not None
    assert SQLAlchemyTweetRepository(db_session).soft_delete(
        tweet.id, actor_id, NOW.replace(hour=13)
    ) is DeleteOutcome.DELETED

    statements: list[str] = []

    def observe(_conn, _cursor, statement, _params, _context, _many):
        statements.append(" ".join(statement.split()).lower())

    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        assert repository.set_state(uuid4(), actor_id, True) is None
        assert repository.set_state(tweet.id, actor_id, False) is None
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)

    assert len(statements) == 2
    assert all("tweet_likes" not in statement for statement in statements)
    with Session(db_session.bind) as independent:
        assert len(independent.execute(select(TweetLikeModel)).scalars().all()) == 1


def test_active_mutation_has_bounded_three_statement_shape(
    db_session: Session,
) -> None:
    actor_id = _user(db_session)
    tweet = _tweet(actor_id)
    SQLAlchemyTweetRepository(db_session).add(tweet)
    statements: list[str] = []

    def observe(_conn, _cursor, statement, _params, _context, _many):
        statements.append(" ".join(statement.split()).lower())

    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        state = SQLAlchemyTweetLikeRepository(db_session).set_state(
            tweet.id, actor_id, True
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)

    assert state is not None and state.like_count == 1
    assert len(statements) == 3
    assert sum("from tweets" in statement and "for update" in statement for statement in statements) == 1
    assert sum("insert into tweet_likes" in statement for statement in statements) == 1
    assert sum("select count(" in statement for statement in statements) == 1


def test_dml_failure_rolls_back_and_session_can_be_reused(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor_id = _user(db_session)
    tweet = _tweet(actor_id)
    SQLAlchemyTweetRepository(db_session).add(tweet)
    repository = SQLAlchemyTweetLikeRepository(db_session)
    original_execute = db_session.execute
    calls = 0

    def fail_dml(statement, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("insert failed")
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", fail_dml)
    with pytest.raises(RuntimeError, match="insert failed"):
        repository.set_state(tweet.id, actor_id, True)
    monkeypatch.undo()

    with Session(db_session.bind) as independent:
        assert independent.execute(select(TweetLikeModel)).scalars().all() == []
    state = repository.set_state(tweet.id, actor_id, True)
    assert state is not None and state.like_count == 1


def test_projection_failure_preserves_prior_state_and_allows_retry(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor_id = _user(db_session)
    tweet = _tweet(actor_id)
    SQLAlchemyTweetRepository(db_session).add(tweet)
    repository = SQLAlchemyTweetLikeRepository(db_session)
    assert repository.set_state(tweet.id, actor_id, True) is not None
    original_execute = db_session.execute
    calls = 0

    def fail_projection(statement, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("projection failed")
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", fail_projection)
    with pytest.raises(RuntimeError, match="projection failed"):
        repository.set_state(tweet.id, actor_id, False)
    monkeypatch.undo()

    with Session(db_session.bind) as independent:
        assert len(independent.execute(select(TweetLikeModel)).scalars().all()) == 1
    state = repository.set_state(tweet.id, actor_id, False)
    assert state is not None and state.like_count == 0
    assert state.liked_by_actor is False


def test_commit_failure_rolls_back_prior_state_and_session_reuse(
    db_session: Session,
) -> None:
    actor_id = _user(db_session)
    tweet = _tweet(actor_id)
    SQLAlchemyTweetRepository(db_session).add(tweet)
    repository = SQLAlchemyTweetLikeRepository(db_session)
    assert repository.set_state(tweet.id, actor_id, True) is not None

    def fail_commit(_session):
        raise RuntimeError("commit failed")

    event.listen(db_session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            repository.set_state(tweet.id, actor_id, False)
    finally:
        event.remove(db_session, "before_commit", fail_commit)

    with Session(db_session.bind) as independent:
        assert len(independent.execute(select(TweetLikeModel)).scalars().all()) == 1
    state = repository.set_state(tweet.id, actor_id, False)
    assert state is not None and state.like_count == 0


def _set_in_independent_session(
    engine, tweet_id: UUID, actor_id: UUID, liked: bool, barrier: threading.Barrier
):
    with Session(engine) as session:
        barrier.wait(timeout=5)
        return SQLAlchemyTweetLikeRepository(session).set_state(
            tweet_id, actor_id, liked
        )


def test_duplicate_posts_serialize_without_duplicate_rows(engine) -> None:
    with Session(engine) as setup:
        _clean(setup)
        actor_id = _user(setup)
        tweet = _tweet(actor_id)
        SQLAlchemyTweetRepository(setup).add(tweet)
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_set_in_independent_session, engine, tweet.id, actor_id, True, barrier)
            for _ in range(2)
        ]
        results = [future.result() for future in futures]

    assert all(result is not None and result.liked_by_actor for result in results)
    assert {result.like_count for result in results} == {1}
    with Session(engine) as verify:
        assert len(verify.execute(select(TweetLikeModel)).scalars().all()) == 1
        _clean(verify)


def test_duplicate_deletes_serialize_without_negative_counts(engine) -> None:
    with Session(engine) as setup:
        _clean(setup)
        actor_id = _user(setup)
        tweet = _tweet(actor_id)
        SQLAlchemyTweetRepository(setup).add(tweet)
        assert SQLAlchemyTweetLikeRepository(setup).set_state(tweet.id, actor_id, True)
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_set_in_independent_session, engine, tweet.id, actor_id, False, barrier)
            for _ in range(2)
        ]
        results = [future.result() for future in futures]

    assert all(result is not None and not result.liked_by_actor for result in results)
    assert {result.like_count for result in results} == {0}
    with Session(engine) as verify:
        assert verify.execute(select(TweetLikeModel)).scalars().all() == []
        _clean(verify)


def test_opposite_requests_have_legal_serial_results(engine) -> None:
    with Session(engine) as setup:
        _clean(setup)
        actor_id = _user(setup)
        tweet = _tweet(actor_id)
        SQLAlchemyTweetRepository(setup).add(tweet)
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        post = pool.submit(
            _set_in_independent_session, engine, tweet.id, actor_id, True, barrier
        )
        delete_request = pool.submit(
            _set_in_independent_session, engine, tweet.id, actor_id, False, barrier
        )
        post_result = post.result()
        delete_result = delete_request.result()

    assert post_result is not None and post_result.liked_by_actor is True
    assert delete_result is not None and delete_result.liked_by_actor is False
    assert {post_result.like_count, delete_result.like_count} == {0, 1}
    with Session(engine) as verify:
        present = verify.execute(select(TweetLikeModel)).scalars().all()
        assert len(present) in {0, 1}
        if present:
            assert (present[0].tweet_public_id, present[0].actor_public_id) == (
                tweet.id,
                actor_id,
            )
        _clean(verify)


def test_different_actors_report_counts_one_and_two(engine) -> None:
    with Session(engine) as setup:
        _clean(setup)
        first = _user(setup)
        second = _user(setup, username="second")
        tweet = _tweet(first)
        SQLAlchemyTweetRepository(setup).add(tweet)
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_set_in_independent_session, engine, tweet.id, actor, True, barrier)
            for actor in (first, second)
        ]
        results = [future.result() for future in futures]

    assert {result.like_count for result in results} == {1, 2}
    with Session(engine) as verify:
        assert len(verify.execute(select(TweetLikeModel)).scalars().all()) == 2
        _clean(verify)


def test_like_and_soft_delete_have_legal_serial_outcomes(engine) -> None:
    with Session(engine) as setup:
        _clean(setup)
        actor_id = _user(setup)
        tweet = _tweet(actor_id)
        SQLAlchemyTweetRepository(setup).add(tweet)

    barrier = threading.Barrier(2)

    def delete_in_independent_session():
        with Session(engine) as session:
            barrier.wait(timeout=5)
            return SQLAlchemyTweetRepository(session).soft_delete(
                tweet.id, actor_id, NOW.replace(hour=13)
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        like_future = pool.submit(
            _set_in_independent_session, engine, tweet.id, actor_id, True, barrier
        )
        delete_future = pool.submit(delete_in_independent_session)
        like_result = like_future.result()
        delete_result = delete_future.result()

    assert delete_result is DeleteOutcome.DELETED
    assert like_result is None or (
        like_result.like_count == 1 and like_result.liked_by_actor is True
    )
    with Session(engine) as verify:
        row = verify.execute(
            select(TweetModel).where(TweetModel.public_id == tweet.id)
        ).scalar_one()
        assert row.deleted_at is not None
        assert len(verify.execute(select(TweetLikeModel)).scalars().all()) == (
            1 if like_result is not None else 0
        )
        _clean(verify)
