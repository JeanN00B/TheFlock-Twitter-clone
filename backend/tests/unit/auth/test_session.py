from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid1

import pytest

from app.auth.domain.session import SESSION_LIFETIME, Session, SessionTokenDigest


VALID_PUBLIC_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
ISSUED_AT = datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone.utc)
DIGEST = b"d" * 32


def test_session_issue_builds_a_fixed_seven_day_digest_bearing_value() -> None:
    digest = SessionTokenDigest(DIGEST)

    session = Session.issue(VALID_PUBLIC_ID, digest, ISSUED_AT)

    assert session.user_public_id == VALID_PUBLIC_ID
    assert session.token_digest is digest
    assert session.issued_at == ISSUED_AT
    assert session.expires_at == datetime(2026, 9, 13, 13, 10, 26, tzinfo=timezone.utc)
    assert session.expires_at == session.issued_at + SESSION_LIFETIME

    with pytest.raises(FrozenInstanceError):
        session.expires_at = ISSUED_AT


@pytest.mark.parametrize("value", [b"short", b"x" * 31, b"x" * 33, "x" * 32])
def test_session_token_digest_requires_exactly_32_bytes(value: object) -> None:
    with pytest.raises(ValueError):
        SessionTokenDigest(value)


def test_session_token_digest_is_frozen_and_keeps_only_the_digest() -> None:
    digest = SessionTokenDigest(DIGEST)

    assert digest.value == DIGEST
    assert {field.name for field in fields(digest)} == {"value"}
    with pytest.raises(FrozenInstanceError):
        digest.value = b"x" * 32


@pytest.mark.parametrize(
    "public_id",
    [uuid1(), "550e8400-e29b-41d4-a716-446655440000"],
)
def test_session_rejects_non_v4_public_id(public_id: object) -> None:
    with pytest.raises(ValueError):
        Session(
            user_public_id=public_id,
            token_digest=SessionTokenDigest(DIGEST),
            issued_at=ISSUED_AT,
            expires_at=ISSUED_AT + timedelta(days=7),
        )


@pytest.mark.parametrize(
    "issued_at",
    [
        datetime(2026, 9, 6, 13, 10, 26),
        datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_session_rejects_naive_or_non_utc_timestamps(issued_at: datetime) -> None:
    with pytest.raises(ValueError):
        Session.issue(VALID_PUBLIC_ID, SessionTokenDigest(DIGEST), issued_at)


def test_session_rejects_any_expiry_other_than_exact_seven_days() -> None:
    with pytest.raises(ValueError):
        Session(
            user_public_id=VALID_PUBLIC_ID,
            token_digest=SessionTokenDigest(DIGEST),
            issued_at=ISSUED_AT,
            expires_at=ISSUED_AT + timedelta(days=7, seconds=1),
        )
