"""SQLAlchemy adapter for privacy-safe public social reads."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.users.application.public_social_reads import PublicIdentity
from app.users.infrastructure.user_model import UserModel


class SQLAlchemyPublicSocialReadRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def search(self, term: str, limit: int) -> tuple[PublicIdentity, ...]:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        statement = (
            select(UserModel.public_id, UserModel.username, UserModel.display_name)
            .where(
                or_(
                    UserModel.username.ilike(pattern, escape="\\"),
                    UserModel.display_name.ilike(pattern, escape="\\"),
                )
            )
            .order_by(UserModel.username.asc(), UserModel.public_id.asc())
            .limit(limit)
        )
        return tuple(PublicIdentity(*row) for row in self._session.execute(statement))
