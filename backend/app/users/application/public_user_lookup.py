"""Users application seam for credential-free public-user reads."""

from typing import Protocol
from uuid import UUID

from app.users.domain.user import PublicUser


class PublicUserLookup(Protocol):
    """Look up a credential-free user projection by public ID."""

    def find_by_public_id(self, public_id: UUID) -> PublicUser | None:
        """Return the public user for the ID, when present."""
