"""Explicit runtime composition for cross-capability application services."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.application.login import Login
from app.auth.infrastructure.login_router import build_login_router
from app.auth.infrastructure.session_store import SQLAlchemySessionStore
from app.auth.infrastructure.session_tokens import (
    SecretsSessionTokenGenerator,
    Sha256SessionTokenHasher,
)
from app.infrastructure.database import get_db
from app.core.settings import get_settings
from app.users.application.credential_lookup import UserCredentialLookup
from app.users.infrastructure.credential_lookup import SQLAlchemyUserCredentialLookup
from app.users.infrastructure.registration_support import (
    SystemClock,
    get_password_hasher,
)


def build_login(session: Session) -> Login:
    """Compose Login from concrete adapters at the application boundary."""

    credential_lookup: UserCredentialLookup = SQLAlchemyUserCredentialLookup(session)
    return Login(
        credential_lookup=credential_lookup,
        password_verifier=get_password_hasher(),
        token_generator=SecretsSessionTokenGenerator(),
        token_hasher=Sha256SessionTokenHasher(),
        clock=SystemClock(),
        session_store=SQLAlchemySessionStore(session),
    )


def get_login(session: Session = Depends(get_db)) -> Login:
    """Provide one composed Login use case for each request."""

    return build_login(session)


def get_session_cookie_secure() -> bool:
    """Read the environment-derived cookie security policy."""

    return get_settings().session_cookie_secure


login_router = build_login_router(get_login, get_session_cookie_secure)
