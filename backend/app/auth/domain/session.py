"""Framework-free session values and lifetime invariants."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


SESSION_LIFETIME = timedelta(days=7)


def _require_uuid4(value: object, field: str) -> None:
    if not isinstance(value, UUID) or value.version != 4:
        raise ValueError(f"{field} must be a UUID v4")


def _require_aware_utc(value: object, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be UTC")


@dataclass(frozen=True, slots=True)
class SessionTokenDigest:
    """A fixed-size SHA-256 digest used as the session persistence key."""

    value: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.value, bytes) or len(self.value) != 32:
            raise ValueError("token digest must be exactly 32 bytes")


@dataclass(frozen=True, slots=True)
class Session:
    """A durable session with an absolute seven-day lifetime."""

    user_public_id: UUID
    token_digest: SessionTokenDigest
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_uuid4(self.user_public_id, "user_public_id")
        if not isinstance(self.token_digest, SessionTokenDigest):
            raise ValueError("token_digest must be a SessionTokenDigest")
        _require_aware_utc(self.issued_at, "issued_at")
        _require_aware_utc(self.expires_at, "expires_at")
        if self.expires_at - self.issued_at != SESSION_LIFETIME:
            raise ValueError("expires_at must be exactly seven days after issued_at")

    @classmethod
    def issue(
        cls,
        user_public_id: UUID,
        token_digest: SessionTokenDigest,
        issued_at: datetime,
    ) -> "Session":
        """Issue one session and calculate its expiry exactly once."""

        _require_aware_utc(issued_at, "issued_at")
        expires_at = issued_at + SESSION_LIFETIME
        return cls(
            user_public_id=user_public_id,
            token_digest=token_digest,
            issued_at=issued_at,
            expires_at=expires_at,
        )
