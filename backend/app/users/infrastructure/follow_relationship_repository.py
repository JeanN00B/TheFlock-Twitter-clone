"""PostgreSQL adapter for idempotent follow transitions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.users.application.follow_relationships import FollowState
from app.users.infrastructure.follow_relationship_model import FollowRelationshipModel
from app.users.infrastructure.user_model import UserModel


class SQLAlchemyFollowRelationshipRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def set_state(self, actor_id: UUID, target_username: str, following: bool, occurred_at: datetime) -> FollowState | None:
        with self._session.begin():
            target = self._session.execute(
                select(UserModel.public_id, UserModel.username).where(UserModel.username == target_username)
            ).one_or_none()
            if target is None:
                return None
            target_id, canonical_username = target
            locked_ids = tuple(sorted((actor_id, target_id), key=str))
            locked = self._session.execute(
                select(UserModel.public_id).where(UserModel.public_id.in_(locked_ids)).order_by(UserModel.public_id).with_for_update()
            ).scalars().all()
            if len(locked) != 2:
                return None
            if following:
                statement = insert(FollowRelationshipModel).values(
                    follower_public_id=actor_id,
                    followed_public_id=target_id,
                    created_at=occurred_at,
                ).on_conflict_do_nothing(constraint="uq_follow_relationships_follower_followed")
                self._session.execute(statement)
            else:
                self._session.execute(
                    delete(FollowRelationshipModel).where(
                        FollowRelationshipModel.follower_public_id == actor_id,
                        FollowRelationshipModel.followed_public_id == target_id,
                    )
                )
        return FollowState(username=canonical_username, following=following)
