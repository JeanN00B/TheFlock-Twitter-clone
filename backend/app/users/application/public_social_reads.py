"""Framework-free application seam for public social reads."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
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


class RelationshipDirection(str, Enum):
    FOLLOWERS = "followers"
    FOLLOWING = "following"


@dataclass(frozen=True)
class RelationshipScope:
    direction: RelationshipDirection
    username: str


@dataclass(frozen=True)
class RelationshipCursor:
    created_at: datetime
    id: UUID


@dataclass(frozen=True)
class ScopedRelationshipCursor:
    scope: RelationshipScope
    boundary: RelationshipCursor


@dataclass(frozen=True)
class RelationshipPage:
    items: tuple[PublicIdentity, ...]
    next_cursor: RelationshipCursor | None


class PublicSocialReadRepository(Protocol):
    def search(self, term: str, limit: int) -> tuple[PublicIdentity, ...]: ...

    def profile(self, username: str, actor_id: UUID) -> PublicProfile | None: ...

    def relationships(
        self, scope: RelationshipScope, boundary: RelationshipCursor | None, limit: int,
    ) -> tuple[tuple[PublicIdentity, ...], tuple[RelationshipCursor, ...]] | None: ...


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


class RelationshipValidationError(Exception):
    def __init__(self, field: str) -> None:
        self.fields = {field: "invalid"}
        super().__init__(self.fields)


class RelationshipTargetNotFound(Exception):
    """The canonical list target does not exist."""


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


class ListPublicRelationships:
    def __init__(self, repository: PublicSocialReadRepository) -> None:
        self._repository = repository

    def execute(
        self,
        username: str,
        direction: RelationshipDirection,
        page_size: int = 20,
        cursor: ScopedRelationshipCursor | None = None,
    ) -> RelationshipPage:
        try:
            canonical_username = canonicalize_username(username)
        except (TypeError, ValueError) as error:
            raise RelationshipValidationError("username") from error
        if not isinstance(direction, RelationshipDirection):
            raise RelationshipValidationError("direction")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 50:
            raise RelationshipValidationError("page_size")
        scope = RelationshipScope(direction, canonical_username)
        if cursor is not None and cursor.scope != scope:
            raise RelationshipValidationError("cursor")
        result = self._repository.relationships(
            scope, cursor.boundary if cursor else None, page_size + 1,
        )
        if result is None:
            raise RelationshipTargetNotFound()
        identities, boundaries = result
        has_more = len(identities) > page_size
        return RelationshipPage(
            identities[:page_size], boundaries[page_size - 1] if has_more else None,
        )


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
