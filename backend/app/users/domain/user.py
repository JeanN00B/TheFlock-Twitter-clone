"""Framework-free user values and registration invariants."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from uuid import UUID

from email_validator import EmailNotValidError, validate_email


_USERNAME_PATTERN = re.compile(r"[a-z0-9_]{3,15}")


def canonicalize_email(value: str) -> str:
    """Trim and lowercase an email without provider-specific rewriting."""

    if not isinstance(value, str):
        raise ValueError("email must be a string")

    canonical = value.strip().lower()
    if not canonical or len(canonical) > 254:
        raise ValueError("email has an invalid length")

    try:
        validate_email(canonical, check_deliverability=False)
    except EmailNotValidError as error:
        raise ValueError("email has invalid syntax") from error

    return canonical


def canonicalize_username(value: str) -> str:
    """Trim and lowercase a username, preserving its exact handle grammar."""

    if not isinstance(value, str):
        raise ValueError("username must be a string")
    if not value.isascii():
        raise ValueError("username must contain ASCII characters")

    canonical = value.strip().lower()
    if _USERNAME_PATTERN.fullmatch(canonical) is None:
        raise ValueError("username has invalid syntax")

    return canonical


def canonicalize_display_name(value: str) -> str:
    """Trim only the outside of a display name and preserve its content."""

    if not isinstance(value, str):
        raise ValueError("display name must be a string")

    canonical = value.strip()
    if not 1 <= len(canonical) <= 50:
        raise ValueError("display name has an invalid length")

    return canonical


def validate_password(value: str) -> str:
    """Validate password length while preserving every submitted character."""

    if not isinstance(value, str):
        raise ValueError("password must be a string")
    if not 8 <= len(value) <= 128:
        raise ValueError("password has an invalid length")

    return value


def _require_aware_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")


@dataclass(frozen=True)
class NewUser:
    """The credential-bearing value sent to the persistence port."""

    public_id: UUID
    email: str
    username: str
    display_name: str
    password_hash: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.public_id, UUID) or self.public_id.version != 4:
            raise ValueError("public_id must be a UUID v4")
        if self.created_at != self.updated_at:
            raise ValueError("registration timestamps must match")
        _require_aware_utc(self.created_at)


@dataclass(frozen=True)
class PublicUser:
    """The credential-free value returned by the registration port."""

    id: UUID
    email: str
    username: str
    display_name: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or self.id.version != 4:
            raise ValueError("id must be a UUID v4")
        if self.created_at != self.updated_at:
            raise ValueError("registration timestamps must match")
        _require_aware_utc(self.created_at)
