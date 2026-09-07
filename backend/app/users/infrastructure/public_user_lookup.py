"""SQLAlchemy adapter for the Users public-user lookup seam."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.users.domain.user import PublicUser
from app.users.infrastructure.user_model import UserModel


class SQLAlchemyPublicUserLookup:
    """Read only the credential-free projection for a public user ID."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_public_id(self, public_id: UUID) -> PublicUser | None:
        """Return a mapped public-user projection and close the read transaction."""

        with self._session.begin():
            selected = self._session.execute(
                select(
                    UserModel.public_id,
                    UserModel.email,
                    UserModel.username,
                    UserModel.display_name,
                    UserModel.created_at,
                    UserModel.updated_at,
                ).where(UserModel.public_id == public_id)
            ).one_or_none()
            if selected is None:
                return None

            (
                selected_public_id,
                email,
                username,
                display_name,
                created_at,
                updated_at,
            ) = selected
            return PublicUser(
                id=selected_public_id,
                email=email,
                username=username,
                display_name=display_name,
                created_at=created_at,
                updated_at=updated_at,
            )
