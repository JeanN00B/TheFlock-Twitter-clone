from datetime import datetime, timezone
from uuid import UUID

from pwdlib import PasswordHash

from app.users.application.register_user import RegisterUser, RegisterUserCommand
from app.users.infrastructure.password_hasher import PwdlibPasswordHasher


PASSWORD = "correct horse battery staple"


def test_hash_returns_argon2id_encoded_value_without_plaintext() -> None:
    encoded = PwdlibPasswordHasher().hash(PASSWORD)

    assert encoded.startswith("$argon2id$")
    assert PASSWORD not in encoded


def test_hashes_use_distinct_salts_and_verify_independently() -> None:
    hasher = PwdlibPasswordHasher()
    verifier = PasswordHash.recommended()

    first = hasher.hash(PASSWORD)
    second = hasher.hash(PASSWORD)

    assert first != second
    assert verifier.verify(PASSWORD, first)
    assert verifier.verify(PASSWORD, second)
    assert not verifier.verify("a different password", first)


class FixedIdentity:
    def new(self) -> UUID:
        return UUID("550e8400-e29b-41d4-a716-446655440000")


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone.utc)


class RecordingRepository:
    def __init__(self) -> None:
        self.user = None

    def add(self, user) -> None:
        self.user = user


def test_registration_public_result_excludes_plaintext_and_encoded_hash() -> None:
    repository = RecordingRepository()
    result = RegisterUser(
        repository=repository,
        password_hasher=PwdlibPasswordHasher(),
        public_id_generator=FixedIdentity(),
        clock=FixedClock(),
    ).execute(
        RegisterUserCommand(
            email="person@example.com",
            username="alice_42",
            display_name="Alice Example",
            password=PASSWORD,
        )
    )

    assert PASSWORD not in repository.user.password_hash
    assert set(vars(result)) == {
        "id",
        "email",
        "username",
        "display_name",
        "created_at",
        "updated_at",
    }
    assert all(PASSWORD not in str(value) for value in vars(result).values())
