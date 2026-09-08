from dataclasses import FrozenInstanceError, fields
from uuid import UUID

import pytest

from app.tweets.application.errors import TweetNotFound
from app.tweets.application.ports import LikeStateRepository
from app.tweets.application.set_like_state import SetLikeState, SetLikeStateCommand
from app.tweets.domain.tweet import LikeState, MAX_LIKE_COUNT


TWEET_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_like_state_accepts_valid_values_and_is_frozen() -> None:
    state = LikeState(tweet_id=TWEET_ID, like_count=9_223_372_036_854_775_807, liked_by_actor=True)

    assert {item.name for item in fields(state)} == {
        "tweet_id",
        "like_count",
        "liked_by_actor",
    }
    assert state.tweet_id == TWEET_ID
    assert state.like_count == 9_223_372_036_854_775_807
    assert state.liked_by_actor is True
    with pytest.raises(FrozenInstanceError):
        state.like_count = 0  # type: ignore[misc]


def test_like_state_accepts_zero_and_false() -> None:
    assert LikeState(tweet_id=TWEET_ID, like_count=0, liked_by_actor=False) == LikeState(
        tweet_id=TWEET_ID, like_count=0, liked_by_actor=False
    )


@pytest.mark.parametrize(
    "tweet_id",
    [
        None,
        "11111111-1111-4111-8111-111111111111",
        UUID("11111111-1111-3111-8111-111111111111"),
        UUID("11111111-1111-5111-8111-111111111111"),
        UUID("11111111-1111-4111-0111-111111111111"),
    ],
)
def test_like_state_rejects_non_rfc4122_uuid4_tweet_ids(tweet_id: object) -> None:
    with pytest.raises(ValueError):
        LikeState(tweet_id=tweet_id, like_count=0, liked_by_actor=False)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "like_count",
    [None, True, False, 0.0, "0", -1, MAX_LIKE_COUNT + 1],
)
def test_like_state_rejects_invalid_counts(like_count: object) -> None:
    with pytest.raises(ValueError):
        LikeState(tweet_id=TWEET_ID, like_count=like_count, liked_by_actor=False)  # type: ignore[arg-type]


@pytest.mark.parametrize("liked_by_actor", [None, 0, 1, "false", object()])
def test_like_state_rejects_non_boolean_actor_state(liked_by_actor: object) -> None:
    with pytest.raises(ValueError):
        LikeState(tweet_id=TWEET_ID, like_count=0, liked_by_actor=liked_by_actor)  # type: ignore[arg-type]


ACTOR_ID = UUID("22222222-2222-4222-8222-222222222222")


def test_set_like_state_command_is_validated_and_frozen() -> None:
    command = SetLikeStateCommand(tweet_id=TWEET_ID, actor_id=ACTOR_ID, liked=True)

    assert command == SetLikeStateCommand(tweet_id=TWEET_ID, actor_id=ACTOR_ID, liked=True)
    with pytest.raises(FrozenInstanceError):
        command.liked = False  # type: ignore[misc]


@pytest.mark.parametrize("field", ["tweet_id", "actor_id"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        "11111111-1111-4111-8111-111111111111",
        UUID("11111111-1111-3111-8111-111111111111"),
        UUID("11111111-1111-5111-8111-111111111111"),
        UUID("11111111-1111-4111-0111-111111111111"),
    ],
)
def test_set_like_state_command_rejects_invalid_uuid_fields(field: str, value: object) -> None:
    values: dict[str, object] = {"tweet_id": TWEET_ID, "actor_id": ACTOR_ID, "liked": True}
    values[field] = value
    with pytest.raises(ValueError):
        SetLikeStateCommand(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("liked", [None, 0, 1, "true", object()])
def test_set_like_state_command_requires_exact_boolean(liked: object) -> None:
    with pytest.raises(ValueError):
        SetLikeStateCommand(tweet_id=TWEET_ID, actor_id=ACTOR_ID, liked=liked)  # type: ignore[arg-type]


class RecordingLikeStateRepository:
    def __init__(self, result: LikeState | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[UUID, UUID, bool]] = []

    def set_state(self, tweet_id: UUID, actor_id: UUID, liked: bool) -> LikeState | None:
        self.calls.append((tweet_id, actor_id, liked))
        if self.error is not None:
            raise self.error
        return self.result


def test_like_state_repository_port_has_atomic_set_state_contract() -> None:
    assert hasattr(LikeStateRepository, "set_state")


def test_set_like_state_returns_authoritative_result_and_calls_port_once() -> None:
    expected = LikeState(tweet_id=TWEET_ID, like_count=3, liked_by_actor=True)
    repository = RecordingLikeStateRepository(result=expected)
    use_case = SetLikeState(repository)
    command = SetLikeStateCommand(tweet_id=TWEET_ID, actor_id=ACTOR_ID, liked=True)

    assert use_case.execute(command) is expected
    assert repository.calls == [(TWEET_ID, ACTOR_ID, True)]


def test_set_like_state_maps_missing_active_tweet_to_existing_error() -> None:
    repository = RecordingLikeStateRepository(result=None)
    use_case = SetLikeState(repository)
    command = SetLikeStateCommand(tweet_id=TWEET_ID, actor_id=ACTOR_ID, liked=False)

    with pytest.raises(TweetNotFound):
        use_case.execute(command)
    assert repository.calls == [(TWEET_ID, ACTOR_ID, False)]


def test_set_like_state_propagates_unexpected_error_identity() -> None:
    failure = RuntimeError("database unavailable")
    repository = RecordingLikeStateRepository(error=failure)
    use_case = SetLikeState(repository)
    command = SetLikeStateCommand(tweet_id=TWEET_ID, actor_id=ACTOR_ID, liked=True)

    with pytest.raises(RuntimeError) as raised:
        use_case.execute(command)
    assert raised.value is failure
    assert repository.calls == [(TWEET_ID, ACTOR_ID, True)]


def test_invalid_command_never_calls_like_state_port() -> None:
    repository = RecordingLikeStateRepository()
    use_case = SetLikeState(repository)

    with pytest.raises(ValueError):
        SetLikeStateCommand(tweet_id="not-a-uuid", actor_id=ACTOR_ID, liked=True)  # type: ignore[arg-type]

    assert repository.calls == []
