"""Framework-free follow relationship application seam."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.users.domain.follow import FollowRequest, InvalidFollowRequest


@dataclass(frozen=True)
class FollowState:
    username: str
    following: bool


@dataclass(frozen=True)
class SetFollowStateCommand:
    actor_id: UUID
    actor_username: str
    target_username: str
    following: bool


class Clock(Protocol):
    def now(self) -> datetime:
        """Return one aware UTC instant for the application occurrence."""


class FollowRelationshipRepository(Protocol):
    def set_state(
        self,
        actor_id: UUID,
        target_username: str,
        following: bool,
        occurred_at: datetime,
    ) -> FollowState | None:
        """Persist the requested state and return its canonical public projection."""


class FollowValidationError(Exception):
    def __init__(self, fields: dict[str, str]) -> None:
        self.fields = fields
        super().__init__(fields)


class UserNotFound(Exception):
    """The canonical target username does not identify a public user."""


class SetFollowState:
    def __init__(self, repository: FollowRelationshipRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    def execute(self, command: SetFollowStateCommand) -> FollowState:
        occurred_at = self._clock.now()
        try:
            request = FollowRequest.validated(
                actor_id=command.actor_id,
                actor_username=command.actor_username,
                target_username=command.target_username,
                following=command.following,
                occurred_at=occurred_at,
            )
        except InvalidFollowRequest as error:
            field = {
                "actor_username": "username",
                "target_username": "username",
            }.get(error.field, error.field)
            raise FollowValidationError({field: "invalid"}) from error

        if request.is_self:
            if request.following:
                raise FollowValidationError({"username": "self_follow"})
            return FollowState(username=request.actor_username, following=False)

        result = self._repository.set_state(
            request.actor_id,
            request.target_username,
            request.following,
            request.occurred_at,
        )
        if result is None:
            raise UserNotFound()
        return result
