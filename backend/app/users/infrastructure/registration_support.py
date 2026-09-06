"""Small framework-independent adapters used by Users registration wiring."""

from datetime import datetime, timezone
from functools import lru_cache
from uuid import UUID, uuid4

from app.users.infrastructure.password_hasher import PwdlibPasswordHasher


class Uuid4Generator:
    """Generate server-owned public UUID v4 identities."""

    def new(self) -> UUID:
        return uuid4()


class SystemClock:
    """Provide the current aware UTC instant."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def get_password_hasher() -> PwdlibPasswordHasher:
    """Reuse one immutable configured password hasher for the process."""

    return PwdlibPasswordHasher()
