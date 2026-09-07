"""Starlette adapter for the one-use committed session-cookie handoff."""

import base64
import binascii

from starlette.responses import Response

from app.auth.application.login import CommittedSessionCookie, RawSessionToken


SESSION_COOKIE_NAME = "flock_session"
SESSION_COOKIE_MAX_AGE = 604800
_RAW_TOKEN_LENGTH = 32
_COOKIE_VALUE_LENGTH = 43
_COOKIE_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def write_session_cookie(
    response: Response,
    committed_cookie: CommittedSessionCookie,
    secure: bool,
) -> None:
    """Consume the committed handoff and set the host-only session cookie once."""

    raw_token, expires_at = committed_cookie.take()
    encoded_token = base64.urlsafe_b64encode(raw_token.as_bytes()).rstrip(b"=").decode(
        "ascii"
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=encoded_token,
        max_age=SESSION_COOKIE_MAX_AGE,
        expires=expires_at,
        path="/",
        domain=None,
        secure=secure,
        httponly=True,
        samesite="lax",
    )


def read_session_cookie(value: str | None) -> RawSessionToken | None:
    """Strictly decode one unpadded base64url session-cookie value.

    Invalid input is deliberately reduced to ``None`` before it reaches the
    application session port.  In particular, no exception contains the
    decoded token bytes.
    """

    if not isinstance(value, str):
        return None
    if len(value) != _COOKIE_VALUE_LENGTH or not value.isascii():
        return None
    if any(character not in _COOKIE_ALPHABET for character in value):
        return None

    try:
        raw_value = base64.b64decode(
            value.encode("ascii") + b"=",
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error):
        return None

    if len(raw_value) != _RAW_TOKEN_LENGTH:
        return None
    canonical_value = base64.urlsafe_b64encode(raw_value).rstrip(b"=")
    if canonical_value != value.encode("ascii"):
        return None

    try:
        return RawSessionToken(raw_value)
    except ValueError:
        return None


def clear_session_cookie(response: Response, secure: bool = False) -> None:
    """Expire the host-only session cookie at the shared root path."""

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        domain=None,
        secure=secure,
        httponly=True,
        samesite="lax",
    )


# Keep the parser/deletion vocabulary discoverable for callers that use the
# protocol names rather than the read/write vocabulary used by login.
parse_session_cookie = read_session_cookie
delete_session_cookie = clear_session_cookie
