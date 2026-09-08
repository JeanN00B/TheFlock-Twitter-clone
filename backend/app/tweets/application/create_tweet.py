"""Create-tweet application orchestration."""

from dataclasses import dataclass
from uuid import UUID

from app.tweets.application.errors import TweetValidationError
from app.tweets.application.ports import Clock, PublicIdGenerator, TweetRepository
from app.tweets.domain.tweet import (
    PublicAuthorSummary,
    PublicTweet,
    Tweet,
    normalize_tweet_text,
)


@dataclass(frozen=True)
class CreateTweetCommand:
    text: str
    author_id: UUID
    author_username: str
    author_display_name: str


class CreateTweet:
    def __init__(
        self,
        repository: TweetRepository,
        public_id_generator: PublicIdGenerator,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._public_id_generator = public_id_generator
        self._clock = clock

    def execute(self, command: CreateTweetCommand) -> PublicTweet:
        try:
            text = normalize_tweet_text(command.text)
        except ValueError as error:
            raise TweetValidationError({"text"}) from error

        tweet = Tweet.create(
            id=self._public_id_generator.new(),
            author_id=command.author_id,
            text=text,
            created_at=self._clock.now(),
        )
        author = PublicAuthorSummary(
            id=command.author_id,
            username=command.author_username,
            display_name=command.author_display_name,
        )
        self._repository.add(tweet)
        return PublicTweet(
            id=tweet.id,
            text=tweet.text,
            created_at=tweet.created_at,
            author=author,
            like_count=0,
            liked_by_actor=False,
        )
