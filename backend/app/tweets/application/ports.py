"""Framework-free outbound ports for tweet use cases."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import re
from typing import Protocol
from uuid import UUID

from app.tweets.domain.tweet import PublicTweet, Tweet


def _validate_uuid4(value: UUID) -> None:
    if type(value) is not UUID or value.version != 4 or value.variant != "specified in RFC 4122":
        raise ValueError("tweet_id must be an RFC 4122 UUID v4")


def _validate_utc(value: datetime) -> None:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != timedelta(0)
    ):
        raise ValueError("created_at must be an aware UTC instant")


class FeedKind(Enum):
    ALL = "all"
    FOLLOWING = "following"
    PROFILE = "profile"


_USERNAME = re.compile(r"^[a-z0-9_]{3,15}$")


@dataclass(frozen=True)
class FeedScope:
    kind: FeedKind
    username: str | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not FeedKind:
            raise ValueError("invalid feed kind")
        if self.kind is FeedKind.PROFILE:
            if type(self.username) is not str or not _USERNAME.fullmatch(self.username):
                raise ValueError("profile feed requires canonical username")
        elif self.username is not None:
            raise ValueError("username is valid only for profile feed")

    @property
    def token(self) -> str:
        if self.kind is FeedKind.PROFILE:
            return f"profile:{self.username}"
        return self.kind.value


@dataclass(frozen=True)
class FeedCursor:
    created_at: datetime
    tweet_id: UUID
    scope: FeedScope = FeedScope(FeedKind.ALL)

    def __post_init__(self) -> None:
        _validate_utc(self.created_at)
        _validate_uuid4(self.tweet_id)
        if type(self.scope) is not FeedScope:
            raise ValueError("invalid feed scope")


class DeleteOutcome(Enum):
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"


class TweetRepository(Protocol):
    def add(self, tweet: Tweet) -> None: ...

    def list_active(
        self, before: FeedCursor | None, limit: int
    ) -> tuple[PublicTweet, ...]: ...

    def soft_delete(
        self, tweet_id: UUID, requester_id: UUID, deleted_at: datetime
    ) -> DeleteOutcome: ...


class PublicIdGenerator(Protocol):
    def new(self) -> UUID: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
