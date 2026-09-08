"""Application-seam tests for bounded public user search."""

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.users.application import public_social_reads
from app.users.application.public_social_reads import (
    SEARCH_RESULT_LIMIT,
    PublicIdentity,
    SearchValidationError,
    SearchUsers,
)

ADA_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
ACTOR_ID = UUID("550e8400-e29b-41d4-a716-446655440001")
INSTANT = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.profile_calls: list[tuple[str, UUID]] = []
        self.results = (PublicIdentity(ADA_ID, "ada_lovelace", "Ada Lovelace"),)
        self.profile_result: object | None = None

    def search(self, term: str, limit: int) -> tuple[PublicIdentity, ...]:
        self.calls.append((term, limit))
        return self.results

    def profile(self, username: str, actor_id: UUID) -> object | None:
        self.profile_calls.append((username, actor_id))
        return self.profile_result

    def relationships(self, scope, boundary, limit):
        self.relationship_calls = getattr(self, "relationship_calls", [])
        self.relationship_calls.append((scope, boundary, limit))
        return getattr(self, "relationship_result", None)


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


def test_profile_canonicalizes_username_and_returns_exact_immutable_projection() -> None:
    repository = RecordingRepository()
    repository.profile_result = public_social_reads.PublicProfile(
        ADA_ID, "ada_lovelace", "Ada Lovelace", 3, 2, True
    )

    result = public_social_reads.GetPublicProfile(repository).execute("  ADA_LOVELACE  ", ACTOR_ID)

    assert result == repository.profile_result
    assert repository.profile_calls == [("ada_lovelace", ACTOR_ID)]
    assert [field.name for field in fields(result)] == [
        "id", "username", "display_name", "followers_count", "following_count",
        "followed_by_actor",
    ]
    assert (result.followers_count, result.following_count, result.followed_by_actor) == (3, 2, True)
    with pytest.raises(FrozenInstanceError):
        result.followers_count = 0  # type: ignore[misc]


@pytest.mark.parametrize("username", ["", "ab", "a-", "@alice", "éclair", None, 42])
def test_profile_rejects_invalid_username_without_repository_call(username: object) -> None:
    repository = RecordingRepository()

    with pytest.raises(public_social_reads.ProfileValidationError) as captured:
        public_social_reads.GetPublicProfile(repository).execute(username, ACTOR_ID)  # type: ignore[arg-type]

    assert captured.value.fields == {"username": "invalid"}
    assert repository.profile_calls == []


def test_profile_maps_missing_target() -> None:
    repository = RecordingRepository()
    repository.profile_result = None

    with pytest.raises(public_social_reads.ProfileNotFound):
        public_social_reads.GetPublicProfile(repository).execute("missing_user", ACTOR_ID)

    assert repository.profile_calls == [("missing_user", ACTOR_ID)]


def test_profile_self_view_preserves_repository_false_state() -> None:
    repository = RecordingRepository()
    repository.profile_result = public_social_reads.PublicProfile(
        ACTOR_ID, "actor_1", "Actor", 1, 1, False
    )

    result = public_social_reads.GetPublicProfile(repository).execute("actor_1", ACTOR_ID)

    assert result.followed_by_actor is False


def test_relationship_list_canonicalizes_scopes_and_uses_lookahead() -> None:
    repository = RecordingRepository()
    identities = tuple(PublicIdentity(UUID(int=index), f"user_{index}", f"User {index}") for index in range(1, 4))
    boundaries = tuple(public_social_reads.RelationshipCursor(INSTANT, item.id) for item in identities)
    repository.relationship_result = (identities, boundaries)

    page = public_social_reads.ListPublicRelationships(repository).execute(
        " ALICE_42 ", public_social_reads.RelationshipDirection.FOLLOWERS, 2, None
    )

    scope = public_social_reads.RelationshipScope(
        public_social_reads.RelationshipDirection.FOLLOWERS, "alice_42"
    )
    assert repository.relationship_calls == [(scope, None, 3)]
    assert page.items == identities[:2]
    assert page.next_cursor == boundaries[1]
    assert [field.name for field in fields(page)] == ["items", "next_cursor"]


@pytest.mark.parametrize("page_size", [0, 51, "1", None])
def test_relationship_list_rejects_invalid_page_size_before_repository(page_size) -> None:
    repository = RecordingRepository()
    with pytest.raises(public_social_reads.RelationshipValidationError) as captured:
        public_social_reads.ListPublicRelationships(repository).execute(
            "alice_42", public_social_reads.RelationshipDirection.FOLLOWING, page_size, None
        )
    assert captured.value.fields == {"page_size": "invalid"}
    assert not hasattr(repository, "relationship_calls")


def test_relationship_list_rejects_cross_scope_cursor_before_repository() -> None:
    repository = RecordingRepository()
    cursor = public_social_reads.ScopedRelationshipCursor(
        public_social_reads.RelationshipScope(
            public_social_reads.RelationshipDirection.FOLLOWERS, "bob_42"
        ),
        public_social_reads.RelationshipCursor(INSTANT, ADA_ID),
    )
    with pytest.raises(public_social_reads.RelationshipValidationError) as captured:
        public_social_reads.ListPublicRelationships(repository).execute(
            "alice_42", public_social_reads.RelationshipDirection.FOLLOWERS, 20, cursor
        )
    assert captured.value.fields == {"cursor": "invalid"}
    assert not hasattr(repository, "relationship_calls")
