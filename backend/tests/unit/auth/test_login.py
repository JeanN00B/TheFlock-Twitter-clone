from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.auth.application.login import (
    Clock,
    CommittedSessionCookie,
    InvalidCredentials,
    Login,
    LoginCommand,
    LoginValidationError,
    PasswordVerifier,
    RawSessionToken,
    SessionStore,
    SessionTokenGenerator,
    SessionTokenHasher,
)
from app.auth.domain.session import Session, SessionTokenDigest
from app.users.application.credential_lookup import UserCredential


PUBLIC_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
PASSWORD_HASH = "encoded-password"
RAW_BYTES = b"r" * 32
DIGEST_BYTES = b"h" * 32
INSTANT = datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone.utc)


class RecordingLookup:
    def __init__(self, events: list[str], credential: UserCredential | None) -> None:
        self.events = events
        self.credential = credential
        self.emails: list[str] = []

    def find_by_canonical_email(self, email: str) -> UserCredential | None:
        self.events.append("lookup")
        self.emails.append(email)
        return self.credential


class RecordingVerifier:
    def __init__(self, events: list[str], result: bool = True) -> None:
        self.events = events
        self.result = result
        self.passwords: list[str] = []

    def verify(self, password: str, encoded_hash: str) -> bool:
        self.events.append("verify")
        self.passwords.append(password)
        assert encoded_hash == PASSWORD_HASH
        return self.result


class RecordingTokenGenerator:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.token = RawSessionToken(RAW_BYTES)

    def generate(self) -> RawSessionToken:
        self.events.append("token")
        return self.token


class RecordingTokenHasher:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.tokens: list[RawSessionToken] = []

    def digest(self, raw_token: RawSessionToken) -> SessionTokenDigest:
        self.events.append("hash")
        self.tokens.append(raw_token)
        return SessionTokenDigest(DIGEST_BYTES)


class RecordingClock:
    def __init__(self, events: list[str], value: datetime = INSTANT) -> None:
        self.events = events
        self.value = value

    def now(self) -> datetime:
        self.events.append("clock")
        return self.value


class RecordingStore:
    def __init__(self, events: list[str], error: Exception | None = None) -> None:
        self.events = events
        self.error = error
        self.sessions: list[Session] = []

    def add_committed(self, session: Session) -> None:
        self.events.append("store")
        if self.error is not None:
            raise self.error
        self.sessions.append(session)


def build_login(
    *,
    events: list[str] | None = None,
    credential: UserCredential | None = UserCredential(PUBLIC_ID, PASSWORD_HASH),
    verified: bool = True,
    clock_value: datetime = INSTANT,
    store_error: Exception | None = None,
) -> tuple[Login, RecordingLookup, RecordingVerifier, RecordingTokenGenerator, RecordingTokenHasher, RecordingClock, RecordingStore]:
    events = [] if events is None else events
    lookup = RecordingLookup(events, credential)
    verifier = RecordingVerifier(events, verified)
    generator = RecordingTokenGenerator(events)
    hasher = RecordingTokenHasher(events)
    clock = RecordingClock(events, clock_value)
    store = RecordingStore(events, store_error)
    return (
        Login(lookup, verifier, generator, hasher, clock, store),
        lookup,
        verifier,
        generator,
        hasher,
        clock,
        store,
    )


@pytest.mark.parametrize("value", [b"short", b"x" * 31, b"x" * 33, "x" * 32])
def test_raw_session_token_requires_exactly_32_bytes(value: object) -> None:
    with pytest.raises(ValueError):
        RawSessionToken(value)


def test_login_canonicalizes_email_preserves_password_and_commits_before_handoff() -> None:
    events: list[str] = []
    login, lookup, verifier, generator, hasher, _, store = build_login(events=events)

    handoff = login.execute(
        LoginCommand(email="  Person@Example.COM  ", password="  exact password\t")
    )

    assert isinstance(handoff, CommittedSessionCookie)
    assert lookup.emails == ["person@example.com"]
    assert verifier.passwords == ["  exact password\t"]
    assert hasher.tokens == [generator.token]
    assert events == ["lookup", "verify", "clock", "token", "hash", "store"]
    assert len(store.sessions) == 1
    assert store.sessions[0].token_digest.value == DIGEST_BYTES
    assert store.sessions[0].issued_at == INSTANT
    assert store.sessions[0].expires_at == INSTANT + timedelta(days=7)

    token, expires_at = handoff.take()
    assert token is generator.token
    assert expires_at == store.sessions[0].expires_at


@pytest.mark.parametrize(
    ("credential", "verified", "expected_events"),
    [
        (None, True, ["lookup"]),
        (UserCredential(PUBLIC_ID, PASSWORD_HASH), False, ["lookup", "verify"]),
    ],
)
def test_absent_and_wrong_credentials_raise_one_generic_error_without_issuance(
    credential: UserCredential | None, verified: bool, expected_events: list[str]
) -> None:
    events: list[str] = []
    login, _, _, _, _, _, store = build_login(
        events=events, credential=credential, verified=verified
    )

    with pytest.raises(InvalidCredentials) as raised:
        login.execute(LoginCommand("person@example.com", "wrong"))

    assert raised.value.args == ()
    assert events == expected_events
    assert store.sessions == []


def test_invalid_canonical_email_fails_before_lookup() -> None:
    events: list[str] = []
    login, _, _, _, _, _, store = build_login(events=events)

    with pytest.raises(LoginValidationError) as raised:
        login.execute(LoginCommand("not-an-email", "short"))

    assert raised.value.fields == {"email": "invalid"}
    assert events == []
    assert store.sessions == []


@pytest.mark.parametrize("password", ["", "short"])
def test_empty_or_short_password_reaches_verifier_without_login_policy(
    password: str,
) -> None:
    events: list[str] = []
    login, _, verifier, _, _, _, store = build_login(events=events, verified=False)

    with pytest.raises(InvalidCredentials):
        login.execute(LoginCommand("person@example.com", password))

    assert verifier.passwords == [password]
    assert events == ["lookup", "verify"]
    assert store.sessions == []


def test_naive_or_non_utc_clock_is_rejected_before_token_generation() -> None:
    for value in (
        datetime(2026, 9, 6, 13, 10, 26),
        datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone(timedelta(hours=1))),
    ):
        events: list[str] = []
        login, _, _, _, _, _, store = build_login(events=events, clock_value=value)

        with pytest.raises(ValueError):
            login.execute(LoginCommand("person@example.com", "password"))

        assert events == ["lookup", "verify", "clock"]
        assert store.sessions == []


def test_store_failure_propagates_without_a_committed_handoff() -> None:
    failure = RuntimeError("storage unavailable")
    events: list[str] = []
    login, _, _, _, _, _, store = build_login(events=events, store_error=failure)

    with pytest.raises(RuntimeError) as raised:
        login.execute(LoginCommand("person@example.com", "password"))

    assert raised.value is failure
    assert events == ["lookup", "verify", "clock", "token", "hash", "store"]
    assert store.sessions == []


def test_store_receives_only_the_digest_bearing_session() -> None:
    login, _, _, generator, _, _, store = build_login()

    login.execute(LoginCommand("person@example.com", "password"))

    session = store.sessions[0]
    assert session.token_digest.value == DIGEST_BYTES
    raw_hex = generator.token.as_bytes().hex()
    assert raw_hex not in repr(session)
    assert session.token_digest.value != generator.token.as_bytes()


def test_cookie_handoff_is_one_use_and_redacts_raw_token() -> None:
    login, _, _, generator, _, _, _ = build_login()
    handoff = login.execute(LoginCommand("person@example.com", "password"))

    assert RAW_BYTES.hex() not in repr(generator.token)
    assert RAW_BYTES.hex() not in repr(handoff)
    assert RAW_BYTES.hex() not in repr(vars(generator.token))
    assert RAW_BYTES.hex() not in repr(vars(handoff))
    token, _ = handoff.take()
    assert token is generator.token

    with pytest.raises(RuntimeError) as raised:
        handoff.take()

    assert RAW_BYTES.hex() not in str(raised.value)
