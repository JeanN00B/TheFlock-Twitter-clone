"""Framework-free application contract for setting tweet like state."""

from dataclasses import dataclass
from uuid import UUID

from app.tweets.application.errors import TweetNotFound
from app.tweets.application.ports import LikeStateRepository
from app.tweets.domain.tweet import LikeState, _require_uuid4


@dataclass(frozen=True)
class SetLikeStateCommand:
    """Validated input for one idempotent like-state mutation."""

    tweet_id: UUID
    actor_id: UUID
    liked: bool

    def __post_init__(self) -> None:
        _require_uuid4(self.tweet_id, "tweet_id")
        _require_uuid4(self.actor_id, "actor_id")
        if type(self.liked) is not bool:
            raise ValueError("liked must be a boolean")


class SetLikeState:
    """Orchestrate one atomic like-state mutation through its repository port."""

    def __init__(self, repository: LikeStateRepository) -> None:
        self._repository = repository

    def execute(self, command: SetLikeStateCommand) -> LikeState:
        state = self._repository.set_state(command.tweet_id, command.actor_id, command.liked)
        if state is None:
            raise TweetNotFound
        return state
