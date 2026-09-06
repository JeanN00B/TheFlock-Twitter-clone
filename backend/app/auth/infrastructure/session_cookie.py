"""Starlette adapter for the one-use committed session-cookie handoff."""

from base64 import urlsafe_b64encode

from starlette.responses import Response

from app.auth.application.login import CommittedSessionCookie


SESSION_COOKIE_NAME = "flock_session"
SESSION_COOKIE_MAX_AGE = 604800


def write_session_cookie(
    response: Response,
    committed_cookie: CommittedSessionCookie,
    secure: bool,
) -> None:
    """Consume the committed handoff and set the host-only session cookie once."""

    raw_token, expires_at = committed_cookie.take()
    encoded_token = urlsafe_b64encode(raw_token.as_bytes()).rstrip(b"=").decode("ascii")
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
