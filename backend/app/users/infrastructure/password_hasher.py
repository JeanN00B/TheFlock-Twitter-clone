"""Pwdlib-backed password hashing adapter for Users."""

from pwdlib import PasswordHash


class PwdlibPasswordHasher:
    """Hash and verify passwords with pwdlib's recommended Argon2id setup."""

    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()

    def hash(self, password: str) -> str:
        """Return a salted, encoded password hash."""

        return self._password_hash.hash(password)

    def verify(self, password: str, encoded_hash: str) -> bool:
        """Verify a password against an encoded hash without rehashing."""

        return self._password_hash.verify(password, encoded_hash)
