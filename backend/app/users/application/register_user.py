"""Framework-free user registration orchestration."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from app.users.domain.user import (
    NewUser,
    PublicUser,
    canonicalize_display_name,
    canonicalize_email,
    canonicalize_username,
    validate_password,
)


_ALLOWED_CONFLICT_FIELDS = frozenset({"email", "username"})


@dataclass(frozen=True)
class RegisterUserCommand:
    """Plain values accepted by the registration application seam."""

    email: str
    username: str
    display_name: str
    password: str


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str:
        """Return the encoded representation of a plaintext password."""


class UserRepository(Protocol):
    def add(self, user: NewUser) -> None:
        """Atomically persist one new user or raise a known conflict."""


class PublicIdGenerator(Protocol):
    def new(self) -> UUID:
        """Return a new public UUID v4."""


class Clock(Protocol):
    def now(self) -> datetime:
        """Return one aware UTC instant."""


class UserWriteConflict(Exception):
    """Repository-level uniqueness feedback for registration."""

    def __init__(self, fields: set[str] | frozenset[str]) -> None:
        normalized = frozenset(fields)
        if not normalized or not normalized <= _ALLOWED_CONFLICT_FIELDS:
            raise ValueError("conflict fields must be email and/or username")
        self.fields = normalized
        super().__init__(normalized)


class RegistrationValidationError(Exception):
    """Application validation failure containing field names only."""

    def __init__(self, fields: dict[str, str]) -> None:
        self.fields = {field: "invalid" for field in fields}
        super().__init__(self.fields)


class RegistrationConflict(Exception):
    """Application-level uniqueness conflict."""

    def __init__(self, fields: set[str] | frozenset[str]) -> None:
        normalized = frozenset(fields)
        if not normalized or not normalized <= _ALLOWED_CONFLICT_FIELDS:
            raise ValueError("conflict fields must be email and/or username")
        self.fields = normalized
        super().__init__(normalized)


class RegisterUser:
    """Deep application interface for one atomic registration."""

    def __init__(
        self,
        repository: UserRepository,
        password_hasher: PasswordHasher,
        public_id_generator: PublicIdGenerator,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._password_hasher = password_hasher
        self._public_id_generator = public_id_generator
        self._clock = clock

    def execute(self, command: RegisterUserCommand) -> PublicUser:
        """Validate, build, persist, and return one credential-free user."""

        fields: dict[str, str] = {}
        canonical: dict[str, str] = {}

        try:
            canonical["email"] = canonicalize_email(command.email)
        except (AttributeError, TypeError, ValueError):
            fields["email"] = "invalid"

        try:
            canonical["username"] = canonicalize_username(command.username)
        except (AttributeError, TypeError, ValueError):
            fields["username"] = "invalid"

        try:
            canonical["display_name"] = canonicalize_display_name(command.display_name)
        except (AttributeError, TypeError, ValueError):
            fields["display_name"] = "invalid"

        try:
            validate_password(command.password)
        except (AttributeError, TypeError, ValueError):
            fields["password"] = "invalid"

        if fields:
            raise RegistrationValidationError(fields)

        public_id = self._public_id_generator.new()
        instant = self._utc(self._clock.now())
        password_hash = self._password_hasher.hash(command.password)
        new_user = NewUser(
            public_id=public_id,
            email=canonical["email"],
            username=canonical["username"],
            display_name=canonical["display_name"],
            password_hash=password_hash,
            created_at=instant,
            updated_at=instant,
        )

        try:
            self._repository.add(new_user)
        except UserWriteConflict as error:
            raise RegistrationConflict(error.fields) from error

        return PublicUser(
            id=new_user.public_id,
            email=new_user.email,
            username=new_user.username,
            display_name=new_user.display_name,
            created_at=new_user.created_at,
            updated_at=new_user.updated_at,
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return an aware UTC instant")
        return value.astimezone(timezone.utc)
