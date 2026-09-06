"""Users application seam for credential-only authentication reads."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class UserCredential:
    """The minimal Users projection required to verify credentials."""

    public_id: UUID
    password_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.public_id, UUID) or self.public_id.version != 4:
            raise ValueError("public_id must be a UUID v4")
        if not isinstance(self.password_hash, str) or not self.password_hash.strip():
            raise ValueError("password_hash must be a non-empty encoded value")


class UserCredentialLookup(Protocol):
    """Look up credentials using an already canonicalized email."""

    def find_by_canonical_email(self, email: str) -> UserCredential | None:
        """Return only credential data for the canonical email, when present."""
