"""Users-owned SQLAlchemy adapters for Tweets feed selection ports."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.tweets.application.ports import ResolvedProfileAuthor
from app.users.infrastructure.follow_relationship_model import FollowRelationshipModel
from app.users.infrastructure.user_model import UserModel


class SQLAlchemyFollowingAudience:
    def __init__(self, session: Session) -> None:
        self._session = session

    def following_ids(self, actor_id: UUID) -> tuple[UUID, ...]:
        statement = select(FollowRelationshipModel.followed_public_id).where(
            FollowRelationshipModel.follower_public_id == actor_id,
            FollowRelationshipModel.followed_public_id != actor_id,
        )
        with self._session.begin():
            return tuple(self._session.execute(statement).scalars())


class SQLAlchemyProfileAuthorResolver:
    def __init__(self, session: Session) -> None:
        self._session = session

    def resolve(self, username: str) -> ResolvedProfileAuthor | None:
        statement = select(UserModel.public_id, UserModel.username).where(
            UserModel.username == username
        )
        with self._session.begin():
            row = self._session.execute(statement).one_or_none()
        return None if row is None else ResolvedProfileAuthor(row.public_id, row.username)
