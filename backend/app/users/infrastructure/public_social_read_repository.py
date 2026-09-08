"""SQLAlchemy adapter for privacy-safe public social reads."""

from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, tuple_
from sqlalchemy.orm import Session, aliased

from app.users.application.public_social_reads import (
    PublicIdentity, PublicProfile, RelationshipCursor, RelationshipDirection,
    RelationshipScope,
)
from app.users.infrastructure.follow_relationship_model import FollowRelationshipModel
from app.users.infrastructure.user_model import UserModel


class SQLAlchemyPublicSocialReadRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def search(self, term: str, limit: int) -> tuple[PublicIdentity, ...]:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        statement = (
            select(UserModel.public_id, UserModel.username, UserModel.display_name)
            .where(or_(
                UserModel.username.ilike(pattern, escape="\\"),
                UserModel.display_name.ilike(pattern, escape="\\"),
            ))
            .order_by(UserModel.username.asc(), UserModel.public_id.asc())
            .limit(limit)
        )
        return tuple(PublicIdentity(*row) for row in self._session.execute(statement))

    def profile(self, username: str, actor_id: UUID) -> PublicProfile | None:
        followers_count = (
            select(func.count()).select_from(FollowRelationshipModel)
            .where(FollowRelationshipModel.followed_public_id == UserModel.public_id)
            .correlate(UserModel).scalar_subquery()
        )
        following_count = (
            select(func.count()).select_from(FollowRelationshipModel)
            .where(FollowRelationshipModel.follower_public_id == UserModel.public_id)
            .correlate(UserModel).scalar_subquery()
        )
        followed_by_actor = and_(
            UserModel.public_id != actor_id,
            exists().where(
                FollowRelationshipModel.follower_public_id == actor_id,
                FollowRelationshipModel.followed_public_id == UserModel.public_id,
            ),
        )
        statement = select(
            UserModel.public_id, UserModel.username, UserModel.display_name,
            followers_count, following_count, followed_by_actor,
        ).where(UserModel.username == username)
        row = self._session.execute(statement).one_or_none()
        return PublicProfile(*row) if row is not None else None

    def relationships(
        self, scope: RelationshipScope, boundary: RelationshipCursor | None, limit: int,
    ) -> tuple[tuple[PublicIdentity, ...], tuple[RelationshipCursor, ...]] | None:
        target_id = self._session.execute(
            select(UserModel.public_id).where(UserModel.username == scope.username)
        ).scalar_one_or_none()
        if target_id is None:
            return None

        related = aliased(UserModel)
        if scope.direction is RelationshipDirection.FOLLOWERS:
            fixed_column = FollowRelationshipModel.followed_public_id
            related_column = FollowRelationshipModel.follower_public_id
        else:
            fixed_column = FollowRelationshipModel.follower_public_id
            related_column = FollowRelationshipModel.followed_public_id
        statement = (
            select(
                related.public_id, related.username, related.display_name,
                FollowRelationshipModel.created_at,
            )
            .join(related, related.public_id == related_column)
            .where(fixed_column == target_id)
            .order_by(FollowRelationshipModel.created_at.desc(), related.public_id.desc())
            .limit(limit)
        )
        if boundary is not None:
            statement = statement.where(tuple_(
                FollowRelationshipModel.created_at, related.public_id,
            ) < (boundary.created_at, boundary.id))
        rows = self._session.execute(statement).all()
        return (
            tuple(PublicIdentity(row[0], row[1], row[2]) for row in rows),
            tuple(RelationshipCursor(row[3], row[0]) for row in rows),
        )
