"""Explicit runtime composition for cross-capability application services."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.application.login import Login
from app.auth.application.session_access import SessionAccess
from app.auth.infrastructure.login_router import build_login_router
from app.auth.infrastructure.session_router import build_session_router
from app.auth.infrastructure.session_store import SQLAlchemySessionStore
from app.auth.infrastructure.session_dependency import build_current_user_dependency
from app.auth.infrastructure.session_tokens import (
    SecretsSessionTokenGenerator,
    Sha256SessionTokenHasher,
)
from app.infrastructure.database import get_db
from app.tweets.application.create_tweet import CreateTweet
from app.tweets.application.delete_tweet import DeleteTweet
from app.tweets.application.list_tweet_feed import ListTweetFeed
from app.tweets.infrastructure.tweet_repository import SQLAlchemyTweetRepository
from app.tweets.infrastructure.tweet_router import build_tweet_router
from app.core.settings import get_settings
from app.users.application.credential_lookup import UserCredentialLookup
from app.users.application.follow_relationships import SetFollowState
from app.users.application.public_social_reads import GetPublicProfile, ListPublicRelationships, SearchUsers
from app.users.infrastructure.credential_lookup import SQLAlchemyUserCredentialLookup
from app.users.infrastructure.follow_relationship_repository import SQLAlchemyFollowRelationshipRepository
from app.users.infrastructure.public_social_read_repository import SQLAlchemyPublicSocialReadRepository
from app.users.infrastructure.public_user_lookup import SQLAlchemyPublicUserLookup
from app.users.infrastructure.user_social_router import build_user_social_router
from app.users.infrastructure.registration_support import (
    SystemClock,
    Uuid4Generator,
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


def build_session_access(session: Session) -> SessionAccess:
    """Compose current-user resolution and revocation from concrete adapters."""

    return SessionAccess(
        session_store=SQLAlchemySessionStore(session),
        public_user_lookup=SQLAlchemyPublicUserLookup(session),
        token_hasher=Sha256SessionTokenHasher(),
        clock=SystemClock(),
    )


def get_session_access(session: Session = Depends(get_db)) -> SessionAccess:
    """Provide one composed SessionAccess use case for each request."""

    return build_session_access(session)


def get_create_tweet(session: Session = Depends(get_db)) -> CreateTweet:
    """Provide one transaction-owning create-tweet use case per request."""

    return CreateTweet(
        repository=SQLAlchemyTweetRepository(session),
        public_id_generator=Uuid4Generator(),
        clock=SystemClock(),
    )


def get_list_tweet_feed(session: Session = Depends(get_db)) -> ListTweetFeed:
    """Provide one global active-tweet feed use case per request."""

    return ListTweetFeed(repository=SQLAlchemyTweetRepository(session))


def get_delete_tweet(session: Session = Depends(get_db)) -> DeleteTweet:
    """Provide one transaction-owning delete-tweet use case per request."""

    return DeleteTweet(repository=SQLAlchemyTweetRepository(session), clock=SystemClock())


def get_search_users(session: Session = Depends(get_db)) -> SearchUsers:
    """Provide one bounded public user search per request."""

    return SearchUsers(SQLAlchemyPublicSocialReadRepository(session))


def get_public_profile(session: Session = Depends(get_db)) -> GetPublicProfile:
    """Provide one privacy-safe public profile read per request."""

    return GetPublicProfile(SQLAlchemyPublicSocialReadRepository(session))


def get_relationship_list(session: Session = Depends(get_db)) -> ListPublicRelationships:
    """Provide one bounded public relationship list per request."""

    return ListPublicRelationships(SQLAlchemyPublicSocialReadRepository(session))


def get_follow_state(session: Session = Depends(get_db)) -> SetFollowState:
    """Provide one transaction-owning follow transition per request."""

    return SetFollowState(
        SQLAlchemyFollowRelationshipRepository(session),
        SystemClock(),
    )


current_user_dependency = build_current_user_dependency(get_session_access)
login_router = build_login_router(get_login, get_session_cookie_secure)
session_router = build_session_router(get_session_access, get_session_cookie_secure)
tweet_router = build_tweet_router(
    get_create_tweet,
    get_list_tweet_feed,
    get_delete_tweet,
    current_user_dependency,
)
user_social_router = build_user_social_router(
    get_follow_state,
    current_user_dependency,
    get_search_users,
    get_public_profile,
    get_relationship_list,
)
