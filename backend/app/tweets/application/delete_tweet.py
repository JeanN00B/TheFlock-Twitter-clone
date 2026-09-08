"""Delete-tweet application orchestration."""

from dataclasses import dataclass
from uuid import UUID

from app.tweets.application.errors import TweetForbidden, TweetNotFound
from app.tweets.application.ports import Clock, DeleteOutcome, TweetRepository


@dataclass(frozen=True)
class DeleteTweetCommand:
    tweet_id: UUID
    requester_id: UUID


class DeleteTweet:
    def __init__(self, repository: TweetRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    def execute(self, command: DeleteTweetCommand) -> None:
        outcome = self._repository.soft_delete(
            command.tweet_id,
            command.requester_id,
            self._clock.now(),
        )
        if outcome is DeleteOutcome.NOT_FOUND:
            raise TweetNotFound
        if outcome is DeleteOutcome.FORBIDDEN:
            raise TweetForbidden
        if outcome is not DeleteOutcome.DELETED:
            raise RuntimeError("repository returned an unknown delete outcome")
