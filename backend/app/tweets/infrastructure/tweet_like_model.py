"""SQLAlchemy persistence model for tweet-like relationships."""

from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, Index, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class TweetLikeModel(Base):
    """Set membership between a tweet and the actor who likes it."""

    __tablename__ = "tweet_likes"
    __table_args__ = (
        PrimaryKeyConstraint(
            "tweet_public_id", "actor_public_id", name="pk_tweet_likes"
        ),
        ForeignKeyConstraint(
            ["tweet_public_id"],
            ["tweets.public_id"],
            name="fk_tweet_likes_tweet_public_id_tweets",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_public_id"],
            ["users.public_id"],
            name="fk_tweet_likes_actor_public_id_users",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_tweet_likes_actor_public_id_tweet_public_id",
            "actor_public_id",
            "tweet_public_id",
        ),
    )

    tweet_public_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    actor_public_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
