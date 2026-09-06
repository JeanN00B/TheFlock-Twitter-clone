"""Framework-free login orchestration and its narrow capability ports."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Protocol

from app.auth.domain.session import Session, SessionTokenDigest
from app.users.application.credential_lookup import UserCredential, UserCredentialLookup
from app.users.domain.user import canonicalize_email


@dataclass(frozen=True, slots=True)
class LoginCommand:
    """Plain values supplied to the login application seam."""

    email: str
    password: str


class LoginValidationError(Exception):
    """Validation failure containing field names, never submitted values."""

    def __init__(self, fields: Mapping[str, str]) -> None:
        self.fields = {field: "invalid" for field in fields}
        super().__init__(self.fields)


class InvalidCredentials(Exception):
    """Generic absent-user or failed-verification marker."""


class PasswordVerifier(Protocol):
    def verify(self, password: str, encoded_hash: str) -> bool:
        """Verify the exact submitted password against an encoded hash."""


class RawSessionToken:
    """A transient 32-byte token whose representations are always redacted."""

    __slots__ = ("_value", "__dict__")

    def __init__(self, value: bytes) -> None:
        if not isinstance(value, bytes) or len(value) != 32:
            raise ValueError("raw session token must be exactly 32 bytes")
        self._value = value

    def as_bytes(self) -> bytes:
        """Return bytes only to the narrow hashing or cookie adapter seam."""

        return self._value

    def __bytes__(self) -> bytes:
        return self._value

    def __repr__(self) -> str:
        return "RawSessionToken(<redacted>)"

    __str__ = __repr__


class SessionTokenGenerator(Protocol):
    def generate(self) -> RawSessionToken:
        """Generate one opaque raw session token."""


class SessionTokenHasher(Protocol):
    def digest(self, raw_token: RawSessionToken) -> SessionTokenDigest:
        """Return the persistence digest for one raw session token."""


class Clock(Protocol):
    def now(self) -> datetime:
        """Return one aware UTC instant."""


class SessionStore(Protocol):
    def add_committed(self, session: Session) -> None:
        """Return only after the session is durably committed."""


class CommittedSessionCookie:
    """A one-use cookie handoff created after session persistence succeeds."""

    __slots__ = ("_raw_token", "_expires_at", "_consumed", "__dict__")

    def __init__(self, raw_token: RawSessionToken, expires_at: datetime) -> None:
        if not isinstance(raw_token, RawSessionToken):
            raise ValueError("raw_token must be a RawSessionToken")
        if (
            not isinstance(expires_at, datetime)
            or expires_at.tzinfo is None
            or expires_at.utcoffset() is None
            or expires_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("expires_at must be aware UTC")
        self._raw_token = raw_token
        self._expires_at = expires_at
        self._consumed = False

    def take(self) -> tuple[RawSessionToken, datetime]:
        """Consume the handoff once, or fail without revealing token data."""

        if self._consumed:
            raise RuntimeError("committed session cookie handoff already consumed")
        self._consumed = True
        return self._raw_token, self._expires_at

    def __repr__(self) -> str:
        return "CommittedSessionCookie(<redacted>)"

    __str__ = __repr__


class Login:
    """Deep application interface for credential verification and issuance."""

    def __init__(
        self,
        credential_lookup: UserCredentialLookup,
        password_verifier: PasswordVerifier,
        token_generator: SessionTokenGenerator,
        token_hasher: SessionTokenHasher,
        clock: Clock,
        session_store: SessionStore,
    ) -> None:
        self._credential_lookup = credential_lookup
        self._password_verifier = password_verifier
        self._token_generator = token_generator
        self._token_hasher = token_hasher
        self._clock = clock
        self._session_store = session_store

    def execute(self, command: LoginCommand) -> CommittedSessionCookie:
        """Verify credentials, commit a session, then return its cookie handoff."""

        try:
            canonical_email = canonicalize_email(command.email)
        except (AttributeError, TypeError, ValueError) as error:
            raise LoginValidationError({"email": "invalid"}) from error

        credential = self._credential_lookup.find_by_canonical_email(canonical_email)
        if credential is None:
            raise InvalidCredentials()

        if not self._password_verifier.verify(command.password, credential.password_hash):
            raise InvalidCredentials()

        issued_at = self._utc(self._clock.now())
        raw_token = self._token_generator.generate()
        token_digest = self._token_hasher.digest(raw_token)
        session = Session.issue(credential.public_id, token_digest, issued_at)
        self._session_store.add_committed(session)
        return CommittedSessionCookie(raw_token, session.expires_at)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError("clock must return an aware UTC instant")
        if value.utcoffset() != timedelta(0):
            raise ValueError("clock must return an aware UTC instant")
        return value.astimezone(timezone.utc)
