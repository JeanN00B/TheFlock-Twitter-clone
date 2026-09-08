"""Framework-free follow relationship application behavior."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.users.application.follow_relationships import (
    FollowState,
    FollowValidationError,
    SetFollowState,
    SetFollowStateCommand,
    UserNotFound,
)

ACTOR_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
INSTANT = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


class FixedClock:
    def __init__(self, value: datetime = INSTANT) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class RecordingRepository:
    def __init__(self, result: FollowState | None = None) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def set_state(self, actor_id, target_username, following, occurred_at):
        self.calls.append((actor_id, target_username, following, occurred_at))
        return self.result


def command(**overrides) -> SetFollowStateCommand:
    values = {
        "actor_id": ACTOR_ID,
        "actor_username": "alice_42",
        "target_username": "  BoB_42  ",
        "following": True,
    }
    values.update(overrides)
    return SetFollowStateCommand(**values)


def use_case_for(
    repository: RecordingRepository,
    occurred_at: datetime = INSTANT,
) -> SetFollowState:
    return SetFollowState(repository, FixedClock(occurred_at))


def test_follow_canonicalizes_target_and_returns_exact_state() -> None:
    repository = RecordingRepository(FollowState(username="bob_42", following=True))
    result = use_case_for(repository).execute(command())
    assert result == FollowState(username="bob_42", following=True)
    assert repository.calls == [(ACTOR_ID, "bob_42", True, INSTANT)]
    assert tuple(result.__dict__) == ("username", "following")


def test_repeated_requested_states_delegate_and_converge() -> None:
    for requested in (True, False):
        expected = FollowState("bob_42", requested)
        repository = RecordingRepository(expected)
        use_case = use_case_for(repository)
        assert use_case.execute(command(following=requested)) == expected
        assert use_case.execute(command(following=requested)) == expected
        assert [call[2] for call in repository.calls] == [requested, requested]


def test_self_follow_is_rejected_before_repository() -> None:
    repository = RecordingRepository()
    with pytest.raises(FollowValidationError) as raised:
        use_case_for(repository).execute(command(target_username=" ALICE_42 "))
    assert raised.value.fields == {"username": "self_follow"}
    assert repository.calls == []


def test_self_unfollow_is_write_free_and_uses_actor_username() -> None:
    repository = RecordingRepository()
    result = use_case_for(repository).execute(
        command(target_username=" ALICE_42 ", following=False)
    )
    assert result == FollowState(username="alice_42", following=False)
    assert repository.calls == []


def test_unknown_target_maps_to_public_not_found() -> None:
    repository = RecordingRepository(None)
    with pytest.raises(UserNotFound):
        use_case_for(repository).execute(command(target_username="nobody"))
    assert repository.calls == [(ACTOR_ID, "nobody", True, INSTANT)]


@pytest.mark.parametrize("target", ["ab", "a" * 16, "Alice-42", "éloise"])
def test_malformed_target_maps_to_username_validation(target: str) -> None:
    repository = RecordingRepository()
    with pytest.raises(FollowValidationError) as raised:
        use_case_for(repository).execute(command(target_username=target))
    assert raised.value.fields == {"username": "invalid"}
    assert repository.calls == []


@pytest.mark.parametrize(
    "occurred_at",
    [
        datetime(2026, 9, 7, 12, 0),
        datetime(2026, 9, 7, 14, 0, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_follow_requires_an_aware_utc_occurrence(occurred_at: datetime) -> None:
    repository = RecordingRepository()
    with pytest.raises(FollowValidationError) as raised:
        use_case_for(repository, occurred_at).execute(command())
    assert raised.value.fields == {"occurred_at": "invalid"}
    assert repository.calls == []
