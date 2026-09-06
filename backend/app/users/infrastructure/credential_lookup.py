"""SQLAlchemy adapter for the Users credential lookup seam."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.users.application.credential_lookup import UserCredential
from app.users.infrastructure.user_model import UserModel


class SQLAlchemyUserCredentialLookup:
    """Read only the credential projection for an already canonical email."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_canonical_email(self, email: str) -> UserCredential | None:
        """Return a mapped credential projection and close the read transaction."""
        with self._session.begin():
            selected = self._session.execute(
                select(UserModel.public_id, UserModel.password_hash).where(
                    UserModel.email == email
                )
            ).one_or_none()
            if selected is None:
                return None
            public_id, password_hash = selected
            return UserCredential(public_id=public_id, password_hash=password_hash)
