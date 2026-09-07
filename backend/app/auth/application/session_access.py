"""Framework-free session resolution and revocation."""

from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from app.auth.application.login import (
    Clock,
    RawSessionToken,
    SessionTokenHasher,
)
from app.auth.domain.session import SessionTokenDigest
from app.users.application.public_user_lookup import PublicUserLookup
from app.users.domain.user import PublicUser


class Unauthenticated(Exception):
    """Generic marker for an absent, expired, or unusable session."""


class SessionAccessStore(Protocol):
    def find_active_user(
        self, token_digest: SessionTokenDigest, now: datetime
    ) -> UUID | None:
        """Return the public ID for an active digest-backed session, when present."""

    def revoke(self, token_digest: SessionTokenDigest) -> None:
        """Delete a digest-backed session, whether or not it exists."""


class SessionAccess:
    """Resolve and revoke opaque session tokens without exposing token material."""

    def __init__(
        self,
        session_store: SessionAccessStore,
        public_user_lookup: PublicUserLookup,
        token_hasher: SessionTokenHasher,
        clock: Clock,
    ) -> None:
        self._session_store = session_store
        self._public_user_lookup = public_user_lookup
        self._token_hasher = token_hasher
        self._clock = clock

    def resolve(self, raw_token: RawSessionToken) -> PublicUser:
        """Return the public user for one active raw token.

        Raise one generic error when the token cannot resolve to a public user.
        """

        now = self._utc(self._clock.now())
        token_digest = self._token_hasher.digest(raw_token)
        public_id = self._session_store.find_active_user(token_digest, now)
        if public_id is None:
            raise Unauthenticated()

        user = self._public_user_lookup.find_by_public_id(public_id)
        if user is None:
            raise Unauthenticated()
        return user

    def revoke(self, raw_token: RawSessionToken) -> None:
        """Hash and delete one raw token; repeated revocation is harmless."""

        token_digest = self._token_hasher.digest(raw_token)
        self._session_store.revoke(token_digest)

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
