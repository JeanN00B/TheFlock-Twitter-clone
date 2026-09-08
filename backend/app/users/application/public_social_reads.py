"""Framework-free application seam for public social reads."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.users.domain.user import canonicalize_username

SEARCH_RESULT_LIMIT = 50


@dataclass(frozen=True)
class PublicIdentity:
    id: UUID
    username: str
    display_name: str


@dataclass(frozen=True)
class PublicProfile:
    id: UUID
    username: str
    display_name: str
    followers_count: int
    following_count: int
    followed_by_actor: bool


class PublicSocialReadRepository(Protocol):
    def search(self, term: str, limit: int) -> tuple[PublicIdentity, ...]: ...

    def profile(self, username: str, actor_id: UUID) -> PublicProfile | None: ...


class SearchValidationError(Exception):
    def __init__(self) -> None:
        self.fields = {"q": "invalid"}
        super().__init__(self.fields)


class ProfileValidationError(Exception):
    def __init__(self) -> None:
        self.fields = {"username": "invalid"}
        super().__init__(self.fields)


class ProfileNotFound(Exception):
    """The canonical username does not identify a public profile."""


class SearchUsers:
    def __init__(self, repository: PublicSocialReadRepository) -> None:
        self._repository = repository

    def execute(self, term: str) -> tuple[PublicIdentity, ...]:
        if not isinstance(term, str):
            raise SearchValidationError()
        normalized = term.strip()
        if not 1 <= len(normalized) <= 50:
            raise SearchValidationError()
        return self._repository.search(normalized, SEARCH_RESULT_LIMIT)


class GetPublicProfile:
    def __init__(self, repository: PublicSocialReadRepository) -> None:
        self._repository = repository

    def execute(self, username: str, actor_id: UUID) -> PublicProfile:
        try:
            canonical_username = canonicalize_username(username)
        except ValueError as error:
            raise ProfileValidationError() from error
        profile = self._repository.profile(canonical_username, actor_id)
        if profile is None:
            raise ProfileNotFound()
        return profile
