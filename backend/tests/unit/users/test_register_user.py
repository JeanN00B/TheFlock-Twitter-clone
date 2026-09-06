from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.users.application.register_user import (
    RegisterUser,
    RegisterUserCommand,
    RegistrationConflict,
    RegistrationValidationError,
    UserWriteConflict,
)


class RecordingIdentity:
    def __init__(self, value: UUID, events: list[str]) -> None:
        self.value = value
        self.events = events

    def new(self) -> UUID:
        self.events.append("identity")
        return self.value


class RecordingClock:
    def __init__(self, value: datetime, events: list[str]) -> None:
        self.value = value
        self.events = events

    def now(self) -> datetime:
        self.events.append("clock")
        return self.value


class RecordingHasher:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.passwords: list[str] = []

    def hash(self, password: str) -> str:
        self.events.append("hash")
        self.passwords.append(password)
        return "encoded-password"


class RecordingRepository:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.users = []
        self.error = None

    def add(self, user) -> None:
        self.events.append("repository")
        if self.error is not None:
            raise self.error
        self.users.append(user)


def build_register_user(
    events: list[str] | None = None,
) -> tuple[RegisterUser, RecordingHasher, RecordingRepository]:
    events = [] if events is None else events
    hasher = RecordingHasher(events)
    repository = RecordingRepository(events)
    register_user = RegisterUser(
        repository=repository,
        password_hasher=hasher,
        public_id_generator=RecordingIdentity(
            UUID("550e8400-e29b-41d4-a716-446655440000"), events
        ),
        clock=RecordingClock(
            datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone.utc), events
        ),
    )
    return register_user, hasher, repository


def test_register_user_executes_the_framework_free_happy_path() -> None:
    events: list[str] = []
    public_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    instant = datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone.utc)
    hasher = RecordingHasher(events)
    repository = RecordingRepository(events)
    register_user = RegisterUser(
        repository=repository,
        password_hasher=hasher,
        public_id_generator=RecordingIdentity(public_id, events),
        clock=RecordingClock(instant, events),
    )

    result = register_user.execute(
        RegisterUserCommand(
            email="  Person+tag@Example.COM  ",
            username="  Alice_42  ",
            display_name="  Ada Lovelace  ",
            password="  exact password  ",
        )
    )

    assert result.id == public_id
    assert result.email == "person+tag@example.com"
    assert result.username == "alice_42"
    assert result.display_name == "Ada Lovelace"
    assert result.created_at == instant
    assert result.updated_at == instant
    assert result.id.version == 4
    assert not hasattr(result, "password")
    assert not hasattr(result, "password_hash")
    assert not hasattr(result, "internal_id")

    assert len(repository.users) == 1
    stored = repository.users[0]
    assert stored.public_id == public_id
    assert stored.email == "person+tag@example.com"
    assert stored.username == "alice_42"
    assert stored.display_name == "Ada Lovelace"
    assert stored.password_hash == "encoded-password"
    assert stored.created_at == instant
    assert stored.updated_at == instant
    assert hasher.passwords == ["  exact password  "]
    assert events == ["identity", "clock", "hash", "repository"]


def test_validation_preserves_the_specified_canonical_values() -> None:
    register_user, hasher, repository = build_register_user()

    result = register_user.execute(
        RegisterUserCommand(
            email="  Person+tag@Example.COM  ",
            username="  Alice_42  ",
            display_name="  Ада  Lovelace  ",
            password="  significant whitespace  ",
        )
    )

    assert result.email == "person+tag@example.com"
    assert result.username == "alice_42"
    assert result.display_name == "Ада  Lovelace"
    assert hasher.passwords == ["  significant whitespace  "]
    assert repository.users[0].email == "person+tag@example.com"


@pytest.mark.parametrize("username", ["ab", "a" * 16, "alice-name", "alice.name", "@alice", "éloise", "Kel"])
def test_invalid_username_grammar_is_rejected(username: str) -> None:
    register_user, hasher, repository = build_register_user()

    with pytest.raises(RegistrationValidationError) as raised:
        register_user.execute(
            RegisterUserCommand(
                email="person@example.com",
                username=username,
                display_name="Alice",
                password="valid pass",
            )
        )

    assert raised.value.fields == {"username": "invalid"}
    assert hasher.passwords == []
    assert repository.users == []


@pytest.mark.parametrize(
    "email",
    ["", "not-an-email", "a@@example.com", "person example.com", "a" * 243 + "@example.com"],
)
def test_invalid_email_syntax_and_length_is_rejected(email: str) -> None:
    register_user, hasher, repository = build_register_user()

    with pytest.raises(RegistrationValidationError) as raised:
        register_user.execute(
            RegisterUserCommand(
                email=email,
                username="alice",
                display_name="Alice",
                password="valid pass",
            )
        )

    assert raised.value.fields == {"email": "invalid"}
    assert hasher.passwords == []
    assert repository.users == []


@pytest.mark.parametrize("display_name", ["", "   ", "x" * 51])
def test_display_name_trimmed_length_is_rejected(display_name: str) -> None:
    register_user, hasher, repository = build_register_user()

    with pytest.raises(RegistrationValidationError) as raised:
        register_user.execute(
            RegisterUserCommand(
                email="person@example.com",
                username="alice",
                display_name=display_name,
                password="valid pass",
            )
        )

    assert raised.value.fields == {"display_name": "invalid"}
    assert hasher.passwords == []
    assert repository.users == []


@pytest.mark.parametrize("password", ["short7", "p" * 129, ""])
def test_password_boundaries_reject_without_normalizing(password: str) -> None:
    register_user, hasher, repository = build_register_user()

    with pytest.raises(RegistrationValidationError) as raised:
        register_user.execute(
            RegisterUserCommand(
                email="person@example.com",
                username="alice",
                display_name="Alice",
                password=password,
            )
        )

    assert raised.value.fields == {"password": "invalid"}
    assert hasher.passwords == []
    assert repository.users == []


def test_validation_collects_all_invalid_fields_before_calling_adapters() -> None:
    events: list[str] = []
    register_user, hasher, repository = build_register_user(events)

    with pytest.raises(RegistrationValidationError) as raised:
        register_user.execute(
            RegisterUserCommand(
                email="not-an-email",
                username="@alice",
                display_name=" ",
                password="short",
            )
        )

    assert raised.value.fields == {
        "email": "invalid",
        "username": "invalid",
        "display_name": "invalid",
        "password": "invalid",
    }
    assert events == []
    assert hasher.passwords == []
    assert repository.users == []


@pytest.mark.parametrize(
    ("conflict_fields", "expected_fields"),
    [
        ({"email"}, frozenset({"email"})),
        ({"username"}, frozenset({"username"})),
        ({"email", "username"}, frozenset({"email", "username"})),
    ],
)
def test_repository_conflicts_are_translated_at_the_application_seam(
    conflict_fields: set[str], expected_fields: frozenset[str]
) -> None:
    events: list[str] = []
    register_user, hasher, repository = build_register_user(events)
    repository.error = UserWriteConflict(conflict_fields)

    with pytest.raises(RegistrationConflict) as raised:
        register_user.execute(
            RegisterUserCommand(
                email="person@example.com",
                username="alice",
                display_name="Alice",
                password="valid pass",
            )
        )

    assert raised.value.fields == expected_fields
    assert not isinstance(raised.value, UserWriteConflict)
    assert events == ["identity", "clock", "hash", "repository"]
    assert len(hasher.passwords) == 1
    assert repository.users == []


def test_unexpected_persistence_failure_propagates_without_a_public_result() -> None:
    register_user, hasher, repository = build_register_user()
    failure = RuntimeError("storage unavailable")
    repository.error = failure

    with pytest.raises(RuntimeError) as raised:
        register_user.execute(
            RegisterUserCommand(
                email="person@example.com",
                username="alice",
                display_name="Alice",
                password="valid pass",
            )
        )

    assert raised.value is failure
    assert len(hasher.passwords) == 1
    assert repository.users == []


def test_public_result_is_constructed_separately_from_persisted_value() -> None:
    register_user, _, repository = build_register_user()

    result = register_user.execute(
        RegisterUserCommand(
            email="person@example.com",
            username="alice",
            display_name="Alice",
            password="valid pass",
        )
    )

    assert result is not repository.users[0]
    assert result.id == repository.users[0].public_id
    assert not {field.name for field in result.__dataclass_fields__.values()} & {
        "password",
        "password_hash",
        "internal_id",
    }


@pytest.mark.parametrize("username", ["abc", "a" * 15])
def test_username_boundary_values_are_accepted(username: str) -> None:
    register_user, _, repository = build_register_user()

    result = register_user.execute(
        RegisterUserCommand(
            email="first.last+tag@example.com",
            username=username,
            display_name="Élodie  Example",
            password="p" * 8,
        )
    )

    assert result.username == username
    assert result.email == "first.last+tag@example.com"
    assert result.display_name == "Élodie  Example"
    assert len(repository.users) == 1


def test_upper_password_boundary_and_fixed_utc_instant_are_preserved() -> None:
    register_user, hasher, repository = build_register_user()
    password = " " + "p" * 126 + " "

    result = register_user.execute(
        RegisterUserCommand(
            email="person@example.com",
            username="alice",
            display_name="A",
            password=password,
        )
    )

    assert len(password) == 128
    assert hasher.passwords == [password]
    assert repository.users[0].created_at == result.created_at
    assert result.created_at == datetime(
        2026, 9, 6, 13, 10, 26, tzinfo=timezone.utc
    )
    assert result.created_at == result.updated_at
