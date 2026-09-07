"""FastAPI adapters for resolving and revoking the current session."""

from collections.abc import Callable

from fastapi import Depends, Request

from app.auth.application.session_access import SessionAccess, Unauthenticated
from app.users.domain.user import PublicUser

from .session_cookie import SESSION_COOKIE_NAME, read_session_cookie


def get_current_user(request: Request, session_access: SessionAccess) -> PublicUser:
    """Resolve the request cookie through the application session port."""

    raw_token = read_session_cookie(request.cookies.get(SESSION_COOKIE_NAME))
    if raw_token is None:
        # SessionAccess owns the generic unauthenticated application error for
        # resolved sessions; the adapter uses the same marker for no cookie.
        raise Unauthenticated()
    return session_access.resolve(raw_token)


def revoke_current_session(request: Request, session_access: SessionAccess) -> None:
    """Revoke a valid request cookie, treating absent input as a no-op."""

    raw_token = read_session_cookie(request.cookies.get(SESSION_COOKIE_NAME))
    if raw_token is not None:
        session_access.revoke(raw_token)


def build_current_user_dependency(
    session_access_provider: Callable[..., SessionAccess],
) -> Callable[..., PublicUser]:
    """Build a reusable FastAPI dependency around a composed SessionAccess."""

    def current_user(
        request: Request,
        session_access: SessionAccess = Depends(session_access_provider),
    ) -> PublicUser:
        return get_current_user(request, session_access)

    return current_user


def build_logout_dependency(
    session_access_provider: Callable[..., SessionAccess],
) -> Callable[..., None]:
    """Build a reusable idempotent logout dependency."""

    def logout(
        request: Request,
        session_access: SessionAccess = Depends(session_access_provider),
    ) -> None:
        revoke_current_session(request, session_access)

    return logout


# Explicit aliases make the two reusable dependency seams clear at call sites.
resolve_current_user = get_current_user
logout_session = revoke_current_session
current_user_dependency = get_current_user
logout_dependency = revoke_current_session
