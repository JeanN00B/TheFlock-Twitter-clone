"""Framework-free follow relationship values and invariants."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.users.domain.user import canonicalize_username


class InvalidFollowRequest(ValueError):
    """Identify which framework-free follow input violated an invariant."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(field)


@dataclass(frozen=True)
class FollowRequest:
    actor_id: UUID
    actor_username: str
    target_username: str
    following: bool
    occurred_at: datetime

    @classmethod
    def validated(
        cls,
        actor_id: UUID,
        actor_username: str,
        target_username: str,
        following: bool,
        occurred_at: datetime,
    ) -> "FollowRequest":
        if not isinstance(actor_id, UUID) or actor_id.version != 4:
            raise InvalidFollowRequest("actor_id")
        try:
            actor = canonicalize_username(actor_username)
        except (AttributeError, TypeError, ValueError) as error:
            raise InvalidFollowRequest("actor_username") from error
        try:
            target = canonicalize_username(target_username)
        except (AttributeError, TypeError, ValueError) as error:
            raise InvalidFollowRequest("target_username") from error
        if not isinstance(following, bool):
            raise InvalidFollowRequest("following")
        if (
            not isinstance(occurred_at, datetime)
            or occurred_at.tzinfo is None
            or occurred_at.utcoffset() != timedelta(0)
        ):
            raise InvalidFollowRequest("occurred_at")
        return cls(actor_id, actor, target, following, occurred_at)

    @property
    def is_self(self) -> bool:
        return self.actor_username == self.target_username
