from datetime import datetime, timezone
from uuid import UUID

import pytest
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.users.application.register_user import RegisterUser, RegisterUserCommand
from app.users.infrastructure.password_hasher import PwdlibPasswordHasher


PASSWORD = "correct horse battery staple"


def test_hash_returns_argon2id_encoded_value_without_plaintext() -> None:
    encoded = PwdlibPasswordHasher().hash(PASSWORD)

    assert encoded.startswith("$argon2id$")
    assert PASSWORD not in encoded


def test_hashes_use_distinct_salts_and_verify_independently() -> None:
    hasher = PwdlibPasswordHasher()

    first = hasher.hash(PASSWORD)
    second = hasher.hash(PASSWORD)

    assert first != second
    assert hasher.verify(PASSWORD, first)
    assert hasher.verify(PASSWORD, second)
    assert not hasher.verify("a different password", first)


def test_verify_preserves_significant_password_whitespace() -> None:
    password = "  exact password\t"
    encoded = PasswordHash.recommended().hash(password)

    hasher = PwdlibPasswordHasher()

    assert hasher.verify(password, encoded)
    assert not hasher.verify(password.strip(), encoded)


def test_verify_propagates_malformed_hash_failures() -> None:
    with pytest.raises(UnknownHashError):
        PwdlibPasswordHasher().verify(PASSWORD, "malformed encoded hash")


def test_hash_and_verify_reuse_one_recommended_password_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    recommended_calls = []
    operations = []

    class RecordingPasswordHash:
        def hash(self, password: str) -> str:
            operations.append(("hash", password))
            return f"encoded:{password}"

        def verify(self, password: str, encoded_hash: str) -> bool:
            operations.append(("verify", password, encoded_hash))
            return encoded_hash == f"encoded:{password}"

    password_hash = RecordingPasswordHash()

    def recommended() -> RecordingPasswordHash:
        recommended_calls.append(password_hash)
        return password_hash

    monkeypatch.setattr(PasswordHash, "recommended", recommended)
    hasher = PwdlibPasswordHasher()

    assert hasher.hash(PASSWORD) == f"encoded:{PASSWORD}"
    assert hasher.verify(PASSWORD, f"encoded:{PASSWORD}")
    assert recommended_calls == [password_hash]
    assert operations == [("hash", PASSWORD), ("verify", PASSWORD, f"encoded:{PASSWORD}")]


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
