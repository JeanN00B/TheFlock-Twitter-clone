"""Pwdlib-backed password hashing adapter for Users."""

from pwdlib import PasswordHash


class PwdlibPasswordHasher:
    """Hash passwords using pwdlib's recommended Argon2id configuration."""

    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()

    def hash(self, password: str) -> str:
        """Return a salted, encoded password hash."""

        return self._password_hash.hash(password)
