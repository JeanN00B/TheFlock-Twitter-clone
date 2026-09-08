"""Application-seam tests for bounded public user search."""

from dataclasses import FrozenInstanceError, fields
from uuid import UUID

import pytest

from app.users.application.public_social_reads import (
    SEARCH_RESULT_LIMIT,
    PublicIdentity,
    SearchValidationError,
    SearchUsers,
)

ADA_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.results = (PublicIdentity(ADA_ID, "ada_lovelace", "Ada Lovelace"),)

    def search(self, term: str, limit: int) -> tuple[PublicIdentity, ...]:
        self.calls.append((term, limit))
        return self.results


def test_search_trims_term_uses_fixed_limit_and_returns_public_identities() -> None:
    repository = RecordingRepository()

    result = SearchUsers(repository).execute("  ADA  ")

    assert result == repository.results
    assert repository.calls == [("ADA", 50)]
    assert SEARCH_RESULT_LIMIT == 50
    assert [field.name for field in fields(result[0])] == ["id", "username", "display_name"]
    with pytest.raises(FrozenInstanceError):
        result[0].username = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("term", ["", "   ", "x" * 51, None, 42])
def test_search_rejects_invalid_term_without_repository_call(term: object) -> None:
    repository = RecordingRepository()

    with pytest.raises(SearchValidationError) as captured:
        SearchUsers(repository).execute(term)  # type: ignore[arg-type]

    assert captured.value.fields == {"q": "invalid"}
    assert repository.calls == []
