from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.auth.application.login import RawSessionToken
from app.auth.application.session_access import SessionAccess, Unauthenticated
from app.auth.domain.session import SessionTokenDigest
from app.users.domain.user import PublicUser


PUBLIC_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
RAW_TOKEN = RawSessionToken(b"r" * 32)
DIGEST = SessionTokenDigest(b"d" * 32)
NOW = datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone.utc)
USER = PublicUser(
    id=PUBLIC_ID,
    email="person@example.com",
    username="person_1",
    display_name="Person Example",
    created_at=NOW,
    updated_at=NOW,
)


class RecordingHasher:
    def __init__(self, digest: SessionTokenDigest = DIGEST) -> None:
        self.digest_value = digest
        self.tokens: list[RawSessionToken] = []

    def digest(self, raw_token: RawSessionToken) -> SessionTokenDigest:
        self.tokens.append(raw_token)
        return self.digest_value


class FixedClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class RecordingSessionStore:
    def __init__(
        self,
        active_user_id: UUID | None,
        session_expires_at: datetime | None = None,
    ) -> None:
        self.active_user_id = active_user_id
        self.session_expires_at = session_expires_at
        self.lookups: list[tuple[SessionTokenDigest, datetime]] = []
        self.revocations: list[SessionTokenDigest] = []

    def find_active_user(
        self, token_digest: SessionTokenDigest, now: datetime
    ) -> UUID | None:
        self.lookups.append((token_digest, now))
        if self.session_expires_at is not None and self.session_expires_at <= now:
            return None
        return self.active_user_id

    def revoke(self, token_digest: SessionTokenDigest) -> None:
        self.revocations.append(token_digest)


class RecordingPublicUserLookup:
    def __init__(self, user: PublicUser | None) -> None:
        self.user = user
        self.public_ids: list[UUID] = []

    def find_by_public_id(self, public_id: UUID) -> PublicUser | None:
        self.public_ids.append(public_id)
        return self.user


def build_access(
    *,
    active_user_id: UUID | None = PUBLIC_ID,
    user: PublicUser | None = USER,
    clock_value: datetime = NOW,
    session_expires_at: datetime | None = None,
) -> tuple[
    SessionAccess,
    RecordingHasher,
    FixedClock,
    RecordingSessionStore,
    RecordingPublicUserLookup,
]:
    hasher = RecordingHasher()
    clock = FixedClock(clock_value)
    store = RecordingSessionStore(active_user_id, session_expires_at)
    lookup = RecordingPublicUserLookup(user)
    access = SessionAccess(
        session_store=store,
        public_user_lookup=lookup,
        token_hasher=hasher,
        clock=clock,
    )
    return access, hasher, clock, store, lookup


def test_resolve_returns_credential_free_public_user_for_active_session() -> None:
    access, hasher, clock, store, lookup = build_access()

    resolved = access.resolve(RAW_TOKEN)

    assert resolved is USER
    assert hasher.tokens == [RAW_TOKEN]
    assert clock.calls == 1
    assert store.lookups == [(DIGEST, NOW)]
    assert lookup.public_ids == [PUBLIC_ID]


@pytest.mark.parametrize(
    ("active_user_id", "session_expires_at"),
    [(None, None), (PUBLIC_ID, NOW)],
    ids=["missing", "expired"],
)
def test_resolve_raises_generic_unauthenticated_for_missing_or_expired_session(
    active_user_id: UUID | None,
    session_expires_at: datetime | None,
) -> None:
    access, hasher, _, store, lookup = build_access(
        active_user_id=active_user_id,
        session_expires_at=session_expires_at,
    )

    with pytest.raises(Unauthenticated) as raised:
        access.resolve(RAW_TOKEN)

    assert raised.value.args == ()
    assert hasher.tokens == [RAW_TOKEN]
    assert len(store.lookups) == 1
    assert lookup.public_ids == []


def test_resolve_raises_generic_unauthenticated_when_user_is_missing() -> None:
    access, _, _, _, lookup = build_access(user=None)

    with pytest.raises(Unauthenticated) as raised:
        access.resolve(RAW_TOKEN)

    assert raised.value.args == ()
    assert lookup.public_ids == [PUBLIC_ID]


def test_resolve_passes_only_hasher_digest_to_the_session_store() -> None:
    access, hasher, _, store, _ = build_access()

    access.resolve(RAW_TOKEN)

    assert hasher.tokens == [RAW_TOKEN]
    digest, _ = store.lookups[0]
    assert digest is DIGEST
    assert RAW_TOKEN.as_bytes() not in digest.value
    assert RAW_TOKEN.as_bytes().hex() not in repr(digest)


def test_revoke_hashes_raw_token_and_is_safe_to_repeat() -> None:
    access, hasher, _, store, _ = build_access()

    access.revoke(RAW_TOKEN)
    access.revoke(RAW_TOKEN)

    assert hasher.tokens == [RAW_TOKEN, RAW_TOKEN]
    assert store.revocations == [DIGEST, DIGEST]


@pytest.mark.parametrize(
    "clock_value",
    [
        datetime(2026, 9, 6, 13, 10, 26),
        datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_resolve_rejects_naive_or_non_utc_clock_before_store_lookup(
    clock_value: datetime,
) -> None:
    access, hasher, _, store, lookup = build_access(clock_value=clock_value)

    with pytest.raises(ValueError, match="aware UTC"):
        access.resolve(RAW_TOKEN)

    assert hasher.tokens == []
    assert store.lookups == []
    assert lookup.public_ids == []
