"""Global active-tweet feed application orchestration."""

from dataclasses import dataclass

from app.tweets.application.errors import TweetValidationError
from app.tweets.application.ports import FeedCursor, TweetRepository
from app.tweets.domain.tweet import PublicTweet


@dataclass(frozen=True)
class ListTweetFeedQuery:
    page_size: int = 20
    before: FeedCursor | None = None


@dataclass(frozen=True)
class TweetPage:
    items: tuple[PublicTweet, ...]
    next_cursor: FeedCursor | None


class ListTweetFeed:
    def __init__(self, repository: TweetRepository) -> None:
        self._repository = repository

    def execute(self, query: ListTweetFeedQuery) -> TweetPage:
        if type(query.page_size) is not int or not 1 <= query.page_size <= 50:
            raise TweetValidationError({"page_size"})
        rows = self._repository.list_active(query.before, query.page_size + 1)
        has_more = len(rows) > query.page_size
        items = rows[: query.page_size]
        next_cursor = None
        if has_more:
            boundary = items[-1]
            next_cursor = FeedCursor(
                created_at=boundary.created_at,
                tweet_id=boundary.id,
            )
        return TweetPage(items=items, next_cursor=next_cursor)
