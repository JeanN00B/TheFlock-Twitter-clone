"""Framework-free application seam for public social reads."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

SEARCH_RESULT_LIMIT = 50


@dataclass(frozen=True)
class PublicIdentity:
    id: UUID
    username: str
    display_name: str


class PublicSocialReadRepository(Protocol):
    def search(self, term: str, limit: int) -> tuple[PublicIdentity, ...]: ...


class SearchValidationError(Exception):
    def __init__(self) -> None:
        self.fields = {"q": "invalid"}
        super().__init__(self.fields)


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
