from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.tweets.domain.tweet import (
    PublicAuthorSummary,
    PublicTweet,
    Tweet,
    normalize_tweet_text,
)


TWEET_ID = UUID("11111111-1111-4111-8111-111111111111")
AUTHOR_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def test_normalization_trims_only_outer_unicode_whitespace() -> None:
    assert normalize_tweet_text("\u2003  hello  world\n  ") == "hello  world"


@pytest.mark.parametrize("value", [None, 42, [], True])
def test_normalization_requires_an_actual_string(value: object) -> None:
    with pytest.raises(ValueError):
        normalize_tweet_text(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", "   \t\n", "\u2003"])
def test_normalization_rejects_empty_content(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_tweet_text(value)


def test_normalization_counts_unicode_code_points_after_trimming() -> None:
    accepted = "🙂" * 280
    assert normalize_tweet_text(f"  {accepted}\n") == accepted
    with pytest.raises(ValueError):
        normalize_tweet_text("🙂" * 281)


def test_new_tweet_has_valid_immutable_lifecycle() -> None:
    tweet = Tweet.create(id=TWEET_ID, author_id=AUTHOR_ID, text="  hello  ", created_at=NOW)

    assert tweet == Tweet(
        id=TWEET_ID,
        author_id=AUTHOR_ID,
        text="hello",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    with pytest.raises(FrozenInstanceError):
        tweet.text = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": UUID("11111111-1111-3111-8111-111111111111")},
        {"author_id": UUID("22222222-2222-4222-0222-222222222222")},
        {"created_at": NOW.replace(tzinfo=None)},
        {"updated_at": NOW.replace(tzinfo=None)},
        {"updated_at": NOW - timedelta(microseconds=1)},
        {"deleted_at": NOW - timedelta(microseconds=1)},
        {"deleted_at": NOW + timedelta(seconds=2), "updated_at": NOW + timedelta(seconds=1)},
    ],
)
def test_rehydration_rejects_invalid_identity_or_lifecycle(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "id": TWEET_ID,
        "author_id": AUTHOR_ID,
        "text": "hello",
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": None,
    }
    values.update(overrides)
    with pytest.raises(ValueError):
        Tweet(**values)  # type: ignore[arg-type]


def test_timestamps_must_be_utc_not_merely_aware() -> None:
    non_utc = NOW.astimezone(timezone(timedelta(hours=2)))
    with pytest.raises(ValueError):
        Tweet.create(id=TWEET_ID, author_id=AUTHOR_ID, text="hello", created_at=non_utc)


def test_public_values_are_frozen_exact_allowlists() -> None:
    author = PublicAuthorSummary(id=AUTHOR_ID, username="alice", display_name="Alice")
    public = PublicTweet(
        id=TWEET_ID,
        text="hello",
        created_at=NOW,
        author=author,
        like_count=0,
        liked_by_actor=False,
    )

    assert {item.name for item in fields(author)} == {"id", "username", "display_name"}
    assert {item.name for item in fields(public)} == {
        "id",
        "text",
        "created_at",
        "author",
        "like_count",
        "liked_by_actor",
    }
    assert public.like_count == 0
    assert public.liked_by_actor is False
    assert not hasattr(public, "updated_at")
    assert not hasattr(public, "deleted_at")
    with pytest.raises(FrozenInstanceError):
        public.text = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PublicAuthorSummary(
            id=UUID("22222222-2222-3222-8222-222222222222"),
            username="alice",
            display_name="Alice",
        ),
        lambda: PublicTweet(
            id=TWEET_ID,
            text="hello",
            created_at=NOW.replace(tzinfo=None),
            author=PublicAuthorSummary(id=AUTHOR_ID, username="alice", display_name="Alice"),
            like_count=0,
            liked_by_actor=False,
        ),
        lambda: PublicTweet(
            id=TWEET_ID,
            text="hello",
            created_at=NOW,
            author=PublicAuthorSummary(id=AUTHOR_ID, username="alice", display_name="Alice"),
            like_count=-1,
            liked_by_actor=False,
        ),
        lambda: PublicTweet(
            id=TWEET_ID,
            text="hello",
            created_at=NOW,
            author=PublicAuthorSummary(id=AUTHOR_ID, username="alice", display_name="Alice"),
            like_count=0,
            liked_by_actor=1,  # type: ignore[arg-type]
        ),
    ],
)
def test_public_values_enforce_public_identity_and_time(factory) -> None:
    with pytest.raises(ValueError):
        factory()
