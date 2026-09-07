"""Framework-free tweet domain values and invariants."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


MAX_TWEET_CODE_POINTS = 280


def normalize_tweet_text(value: str) -> str:
    """Trim outer Unicode whitespace and enforce the tweet content boundary."""
    if type(value) is not str:
        raise ValueError("tweet text must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("tweet text must not be empty")
    if len(normalized) > MAX_TWEET_CODE_POINTS:
        raise ValueError("tweet text must not exceed 280 code points")
    return normalized


def _require_uuid4(value: UUID, field: str) -> None:
    if type(value) is not UUID or value.version != 4 or value.variant != "specified in RFC 4122":
        raise ValueError(f"{field} must be an RFC 4122 UUID v4")


def _require_utc(value: datetime, field: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be UTC")


@dataclass(frozen=True)
class Tweet:
    """Internal immutable tweet lifecycle value."""

    id: UUID
    author_id: UUID
    text: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    def __post_init__(self) -> None:
        _require_uuid4(self.id, "id")
        _require_uuid4(self.author_id, "author_id")
        normalized = normalize_tweet_text(self.text)
        if normalized != self.text:
            raise ValueError("rehydrated tweet text must already be normalized")
        _require_utc(self.created_at, "created_at")
        _require_utc(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.deleted_at is not None:
            _require_utc(self.deleted_at, "deleted_at")
            if self.deleted_at < self.created_at or self.deleted_at > self.updated_at:
                raise ValueError("deleted_at must be between created_at and updated_at")

    @classmethod
    def create(cls, *, id: UUID, author_id: UUID, text: str, created_at: datetime) -> "Tweet":
        normalized = normalize_tweet_text(text)
        return cls(
            id=id,
            author_id=author_id,
            text=normalized,
            created_at=created_at,
            updated_at=created_at,
            deleted_at=None,
        )


@dataclass(frozen=True)
class PublicAuthorSummary:
    """Exact public author allowlist."""

    id: UUID
    username: str
    display_name: str

    def __post_init__(self) -> None:
        _require_uuid4(self.id, "author.id")


@dataclass(frozen=True)
class PublicTweet:
    """Exact public tweet allowlist."""

    id: UUID
    text: str
    created_at: datetime
    author: PublicAuthorSummary

    def __post_init__(self) -> None:
        _require_uuid4(self.id, "id")
        normalized = normalize_tweet_text(self.text)
        if normalized != self.text:
            raise ValueError("public tweet text must already be normalized")
        _require_utc(self.created_at, "created_at")
        if type(self.author) is not PublicAuthorSummary:
            raise ValueError("author must be a public author summary")
