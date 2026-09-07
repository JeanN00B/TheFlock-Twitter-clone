"""Application settings loaded from the process environment."""

import os
from functools import lru_cache
from typing import Literal
from ipaddress import IPv4Address, IPv6Address
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_DEFAULT_HTTP_PORTS = {"http": 80, "https": 443}
_DEFAULT_FRONTEND_ORIGIN = "http://localhost:3000"


def normalize_origin(origin: str) -> str:
    """Return the canonical form of one concrete HTTP(S) origin."""

    if not isinstance(origin, str) or not origin or origin != origin.strip():
        raise ValueError("browser origin must be a concrete HTTP(S) origin")
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in origin):
        raise ValueError("browser origin must not contain whitespace or control characters")
    if "*" in origin or "?" in origin or "#" in origin or "\\" in origin:
        raise ValueError("browser origin must not contain wildcards or URL components")

    parsed = urlsplit(origin)
    scheme = parsed.scheme.lower()
    if scheme not in _DEFAULT_HTTP_PORTS or not parsed.netloc or parsed.netloc.endswith(":"):
        raise ValueError("browser origin must use HTTP or HTTPS")
    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError("browser origin must not contain a path, query, or fragment")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("browser origin must not contain credentials")

    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("allowed origin has an invalid host or port") from error
    if not hostname or any(character.isspace() for character in hostname):
        raise ValueError("allowed origin must contain a valid host")

    normalized_host = _normalize_hostname(hostname)
    if port is not None and not 0 <= port <= 65535:
        raise ValueError("allowed origin has an invalid port")
    normalized_port = "" if port in (None, _DEFAULT_HTTP_PORTS[scheme]) else f":{port}"
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    return f"{scheme}://{normalized_host}{normalized_port}"


def _normalize_hostname(hostname: str) -> str:
    if "*" in hostname or any(character in hostname for character in "/?#@"):
        raise ValueError("allowed origin must contain a valid host")

    try:
        if ":" in hostname:
            return IPv6Address(hostname).compressed.lower()
        return str(IPv4Address(hostname))
    except ValueError:
        pass

    if len(hostname) > 253 or hostname.endswith(".") and len(hostname) > 254:
        raise ValueError("allowed origin host is too long")
    labels = hostname.rstrip(".").split(".")
    if not labels or any(not label for label in labels):
        raise ValueError("allowed origin host is invalid")
    normalized_labels = []
    for label in labels:
        try:
            ascii_label = label.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise ValueError("allowed origin host is invalid") from error
        if (
            len(ascii_label) > 63
            or ascii_label.startswith("-")
            or ascii_label.endswith("-")
            or not all(character.isalnum() or character == "-" for character in ascii_label)
        ):
            raise ValueError("allowed origin host is invalid")
        normalized_labels.append(ascii_label)
    return ".".join(normalized_labels) + ("." if hostname.endswith(".") else "")


def get_frontend_origin() -> str:
    """Return the normalized browser origin configured by Next.js."""

    return normalize_origin(os.getenv("NEXT_PUBLIC_APP_URL", _DEFAULT_FRONTEND_ORIGIN))


class Settings(BaseSettings):
    """Runtime configuration for the backend application."""

    app_environment: Literal["development", "production"] = "development"
    next_public_app_url: str = _DEFAULT_FRONTEND_ORIGIN
    database_url: str
    auto_migrate: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
        validate_default=True,
    )

    @field_validator("next_public_app_url")
    @classmethod
    def normalize_next_public_app_url(cls, value: str) -> str:
        """Keep the configured browser origin in canonical exact-origin form."""

        return normalize_origin(value)

    @model_validator(mode="after")
    def require_https_browser_origin_in_production(self) -> "Settings":
        """Reject production cookies configured for an insecure browser origin."""

        if (
            self.app_environment == "production"
            and urlsplit(self.next_public_app_url).scheme != "https"
        ):
            raise ValueError("production requires NEXT_PUBLIC_APP_URL to use HTTPS")
        return self

    @property
    def session_cookie_secure(self) -> bool:
        """Return the fixed cookie Secure policy for the selected environment."""

        return self.app_environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""

    return Settings()
