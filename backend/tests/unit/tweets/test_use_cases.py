from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.tweets.application.create_tweet import CreateTweet, CreateTweetCommand
from app.tweets.application.delete_tweet import DeleteTweet, DeleteTweetCommand
from app.tweets.application.errors import TweetForbidden, TweetNotFound, TweetValidationError
from app.tweets.application.list_tweet_feed import ListTweetFeed, ListTweetFeedQuery
from app.tweets.application.ports import DeleteOutcome, FeedCursor
from app.tweets.domain.tweet import PublicAuthorSummary, PublicTweet, Tweet


ID_1 = UUID("11111111-1111-4111-8111-111111111111")
ID_2 = UUID("22222222-2222-4222-8222-222222222222")
AUTHOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
AUTHOR = PublicAuthorSummary(id=AUTHOR_ID, username="alice", display_name="Alice")


class RecordingIds:
    def __init__(self, values: list[UUID]) -> None:
        self.values = iter(values)
        self.calls = 0

    def new(self) -> UUID:
        self.calls += 1
        return next(self.values)


class RecordingClock:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class RecordingRepository:
    def __init__(self) -> None:
        self.added: list[Tweet] = []
        self.list_result: tuple[PublicTweet, ...] = ()
        self.list_calls: list[tuple[FeedCursor | None, int]] = []
        self.delete_outcome = DeleteOutcome.DELETED
        self.delete_calls: list[tuple[UUID, UUID, datetime]] = []
        self.events: list[str] = []
        self.add_error: Exception | None = None

    def add(self, tweet: Tweet) -> None:
        self.events.append("commit")
        if self.add_error:
            raise self.add_error
        self.added.append(tweet)

    def list_active(self, before: FeedCursor | None, limit: int) -> tuple[PublicTweet, ...]:
        self.list_calls.append((before, limit))
        return self.list_result

    def soft_delete(
        self, tweet_id: UUID, requester_id: UUID, deleted_at: datetime
    ) -> DeleteOutcome:
        self.delete_calls.append((tweet_id, requester_id, deleted_at))
        return self.delete_outcome


def public_tweet(tweet_id: UUID, created_at: datetime = NOW) -> PublicTweet:
    return PublicTweet(id=tweet_id, text="hello", created_at=created_at, author=AUTHOR)


def build_create(ids: list[UUID] | None = None):
    repository = RecordingRepository()
    generator = RecordingIds(ids or [ID_1])
    clock = RecordingClock(NOW)
    return CreateTweet(repository, generator, clock), repository, generator, clock


def command(text: object = " hello ") -> CreateTweetCommand:
    return CreateTweetCommand(
        text=text,  # type: ignore[arg-type]
        author_id=AUTHOR_ID,
        author_username="alice",
        author_display_name="Alice",
    )


def test_create_uses_actor_identity_one_id_one_instant_and_commits_first() -> None:
    use_case, repository, ids, clock = build_create()

    result = use_case.execute(command())

    assert repository.events == ["commit"]
    assert ids.calls == clock.calls == 1
    assert repository.added == [
        Tweet.create(id=ID_1, author_id=AUTHOR_ID, text="hello", created_at=NOW)
    ]
    assert result == public_tweet(ID_1)
    assert result.author == AUTHOR


def test_create_rejects_invalid_text_before_side_effects() -> None:
    use_case, repository, ids, clock = build_create()
    with pytest.raises(TweetValidationError) as raised:
        use_case.execute(command(" \u2003 "))
    assert raised.value.fields == {"text": "invalid"}
    assert not repository.added
    assert ids.calls == clock.calls == 0


def test_create_propagates_commit_failure_without_public_result() -> None:
    use_case, repository, _, _ = build_create()
    failure = RuntimeError("storage unavailable")
    repository.add_error = failure
    with pytest.raises(RuntimeError) as raised:
        use_case.execute(command())
    assert raised.value is failure


def test_two_creations_generate_distinct_ids() -> None:
    use_case, repository, ids, clock = build_create([ID_1, ID_2])
    assert use_case.execute(command()).id == ID_1
    assert use_case.execute(command("second")).id == ID_2
    assert ids.calls == clock.calls == 2
    assert len(repository.added) == 2


@pytest.mark.parametrize("page_size", [1, 50])
def test_list_requests_one_lookahead_and_returns_cursor_only_for_more(page_size: int) -> None:
    repository = RecordingRepository()
    rows = tuple(
        public_tweet(
            UUID(f"00000000-0000-4000-8000-{index:012d}"),
            NOW - timedelta(seconds=index),
        )
        for index in range(page_size + 1)
    )
    repository.list_result = rows
    before = FeedCursor(created_at=NOW + timedelta(seconds=1), tweet_id=ID_2)

    page = ListTweetFeed(repository).execute(ListTweetFeedQuery(page_size=page_size, before=before))

    assert repository.list_calls == [(before, page_size + 1)]
    assert page.items == rows[:page_size]
    assert page.next_cursor == FeedCursor(
        created_at=rows[page_size - 1].created_at,
        tweet_id=rows[page_size - 1].id,
    )


@pytest.mark.parametrize("rows", [(), (public_tweet(ID_1),)])
def test_list_empty_or_final_page_has_no_cursor(rows: tuple[PublicTweet, ...]) -> None:
    repository = RecordingRepository()
    repository.list_result = rows
    page = ListTweetFeed(repository).execute(ListTweetFeedQuery(page_size=20))
    assert page.items == rows
    assert page.next_cursor is None
    assert repository.list_calls == [(None, 21)]


@pytest.mark.parametrize("page_size", [0, 51, True, 1.5, "20"])
def test_list_rejects_invalid_page_size_without_query(page_size: object) -> None:
    repository = RecordingRepository()
    with pytest.raises(TweetValidationError) as raised:
        ListTweetFeed(repository).execute(ListTweetFeedQuery(page_size=page_size))  # type: ignore[arg-type]
    assert raised.value.fields == {"page_size": "invalid"}
    assert repository.list_calls == []


def test_feed_cursor_rejects_non_utc_or_non_v4_boundary() -> None:
    with pytest.raises(ValueError):
        FeedCursor(created_at=NOW.replace(tzinfo=None), tweet_id=ID_1)
    with pytest.raises(ValueError):
        FeedCursor(
            created_at=NOW.astimezone(timezone(timedelta(hours=2))),
            tweet_id=ID_1,
        )
    with pytest.raises(ValueError):
        FeedCursor(
            created_at=NOW,
            tweet_id=UUID("11111111-1111-3111-8111-111111111111"),
        )


def test_same_time_feed_boundary_uses_last_returned_uuid() -> None:
    repository = RecordingRepository()
    repository.list_result = (public_tweet(ID_2), public_tweet(ID_1))
    page = ListTweetFeed(repository).execute(ListTweetFeedQuery(page_size=1))
    assert page.items == (public_tweet(ID_2),)
    assert page.next_cursor == FeedCursor(created_at=NOW, tweet_id=ID_2)


@pytest.mark.parametrize(
    ("outcome", "expected_error"),
    [
        (DeleteOutcome.DELETED, None),
        (DeleteOutcome.NOT_FOUND, TweetNotFound),
        (DeleteOutcome.FORBIDDEN, TweetForbidden),
    ],
)
def test_delete_maps_atomic_repository_outcome(outcome, expected_error) -> None:
    repository = RecordingRepository()
    repository.delete_outcome = outcome
    clock = RecordingClock(NOW)
    use_case = DeleteTweet(repository, clock)
    delete_command = DeleteTweetCommand(tweet_id=ID_1, requester_id=AUTHOR_ID)

    if expected_error:
        with pytest.raises(expected_error):
            use_case.execute(delete_command)
    else:
        assert use_case.execute(delete_command) is None

    assert repository.delete_calls == [(ID_1, AUTHOR_ID, NOW)]
    assert clock.calls == 1
