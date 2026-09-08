"""Active-tweet feed application orchestration."""

from dataclasses import dataclass
from uuid import UUID

from app.tweets.application.errors import TweetNotFound, TweetValidationError
from app.tweets.application.ports import (
    FeedCursor,
    FeedKind,
    FeedScope,
    FollowingAudience,
    ProfileAuthorResolver,
    TweetRepository,
)
from app.tweets.domain.tweet import PublicTweet


@dataclass(frozen=True)
class ListTweetFeedQuery:
    page_size: int = 20
    before: FeedCursor | None = None
    scope: FeedScope = FeedScope(FeedKind.ALL)
    actor_id: UUID | None = None


@dataclass(frozen=True)
class TweetPage:
    items: tuple[PublicTweet, ...]
    next_cursor: FeedCursor | None


class ListTweetFeed:
    def __init__(
        self,
        repository: TweetRepository,
        audience: FollowingAudience | None = None,
        profile_resolver: ProfileAuthorResolver | None = None,
    ) -> None:
        self._repository = repository
        self._audience = audience
        self._profile_resolver = profile_resolver

    def execute(self, query: ListTweetFeedQuery) -> TweetPage:
        if type(query.page_size) is not int or not 1 <= query.page_size <= 50:
            raise TweetValidationError({"page_size"})
        if type(query.scope) is not FeedScope:
            raise TweetValidationError({"feed"})
        if query.before is not None and query.before.scope != query.scope:
            raise TweetValidationError({"cursor"})

        author_ids: tuple[UUID, ...] | None = None
        if query.scope.kind is FeedKind.FOLLOWING:
            if query.actor_id is None or self._audience is None:
                raise TweetValidationError({"feed"})
            author_ids = tuple(dict.fromkeys(
                value for value in self._audience.following_ids(query.actor_id)
                if value != query.actor_id
            ))
            if not author_ids:
                return TweetPage(items=(), next_cursor=None)
        elif query.scope.kind is FeedKind.PROFILE:
            if self._profile_resolver is None:
                raise TweetValidationError({"feed"})
            resolved = self._profile_resolver.resolve(query.scope.username or "")
            if resolved is None:
                raise TweetNotFound
            author_ids = (resolved.id,)

        rows = self._repository.list_active(query.before, query.page_size + 1, author_ids)
        has_more = len(rows) > query.page_size
        items = rows[: query.page_size]
        next_cursor = None
        if has_more:
            boundary = items[-1]
            next_cursor = FeedCursor(
                created_at=boundary.created_at,
                tweet_id=boundary.id,
                scope=query.scope,
            )
        return TweetPage(items=items, next_cursor=next_cursor)
