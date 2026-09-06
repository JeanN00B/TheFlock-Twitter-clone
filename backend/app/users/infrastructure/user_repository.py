"""SQLAlchemy Users repository adapter."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.users.application.register_user import UserWriteConflict
from app.users.domain.user import NewUser
from app.users.infrastructure.user_model import UserModel


class SQLAlchemyUserRepository:
    """Persist registration users with PostgreSQL as conflict authority."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user: NewUser) -> None:
        """Persist one user atomically or raise a known conflict."""
        with self._session.begin():
            existing = (
                self._session.execute(
                    select(UserModel).where(
                        (UserModel.email == user.email) | (UserModel.username == user.username)
                    )
                )
                .scalars()
                .all()
            )
            conflicting: set[str] = set()
            for row in existing:
                if row.email == user.email:
                    conflicting.add("email")
                if row.username == user.username:
                    conflicting.add("username")
            if conflicting:
                raise UserWriteConflict(conflicting)

            self._session.add(
                UserModel(
                    public_id=user.public_id,
                    email=user.email,
                    username=user.username,
                    display_name=user.display_name,
                    password_hash=user.password_hash,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )
            )
            try:
                self._session.flush()
            except IntegrityError as error:
                constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                if constraint == "uq_users_email":
                    raise UserWriteConflict({"email"}) from error
                if constraint == "uq_users_username":
                    raise UserWriteConflict({"username"}) from error
                raise
