from dataclasses import FrozenInstanceError, fields
from uuid import UUID, uuid1, uuid4

import pytest

from app.users.application.credential_lookup import UserCredential


VALID_PUBLIC_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
VALID_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$somesalt$somehashvalue"


def test_user_credential_is_a_frozen_credential_only_projection() -> None:
    credential = UserCredential(
        public_id=VALID_PUBLIC_ID,
        password_hash=VALID_PASSWORD_HASH,
    )

    assert {field.name for field in fields(credential)} == {"public_id", "password_hash"}
    assert credential.public_id == VALID_PUBLIC_ID
    assert credential.public_id.version == 4
    assert credential.password_hash == VALID_PASSWORD_HASH
    assert not hasattr(credential, "id")
    assert not hasattr(credential, "email")
    assert not hasattr(credential, "username")
    assert not hasattr(credential, "internal_id")

    with pytest.raises(FrozenInstanceError):
        credential.password_hash = "another-hash"


def test_user_credential_accepts_a_distinct_v4_credential_pair() -> None:
    credential = UserCredential(
        public_id=UUID("6ba7b810-9dad-41d1-80b4-00c04fd430c8"),
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$other$encoded",
    )

    assert credential.public_id.version == 4
    assert credential.password_hash.endswith("$encoded")


@pytest.mark.parametrize(
    ("public_id", "password_hash"),
    [
        (uuid1(), VALID_PASSWORD_HASH),
        (VALID_PUBLIC_ID, ""),
        (VALID_PUBLIC_ID, "   "),
        (VALID_PUBLIC_ID, None),
    ],
)
def test_user_credential_rejects_non_v4_or_empty_encoded_credentials(
    public_id: UUID, password_hash: str | None
) -> None:
    with pytest.raises(ValueError):
        UserCredential(public_id=public_id, password_hash=password_hash)


def test_user_credential_rejects_non_uuid_public_id() -> None:
    with pytest.raises(ValueError):
        UserCredential(public_id=uuid4().hex, password_hash=VALID_PASSWORD_HASH)
