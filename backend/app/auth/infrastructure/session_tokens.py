"""Cryptographic adapters for opaque Auth session tokens."""

import hashlib
import secrets

from app.auth.application.login import RawSessionToken
from app.auth.domain.session import SessionTokenDigest


class SecretsSessionTokenGenerator:
    """Generate one cryptographically random, transient session token."""

    def generate(self) -> RawSessionToken:
        """Return exactly 32 random bytes in the redacted application wrapper."""

        return RawSessionToken(secrets.token_bytes(32))


class Sha256SessionTokenHasher:
    """Hash a raw session token for digest-only persistence."""

    def digest(self, raw_token: RawSessionToken) -> SessionTokenDigest:
        """Return the exact 32-byte SHA-256 digest of the token."""

        return SessionTokenDigest(hashlib.sha256(raw_token.as_bytes()).digest())
