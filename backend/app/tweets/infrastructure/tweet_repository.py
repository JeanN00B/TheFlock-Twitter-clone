"""SQLAlchemy adapter for tweet persistence and timeline reads."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.tweets.application.ports import DeleteOutcome, FeedCursor
from app.tweets.domain.tweet import PublicAuthorSummary, PublicTweet, Tweet
from app.tweets.infrastructure.tweet_model import TweetModel
from app.users.infrastructure.user_model import UserModel


class SQLAlchemyTweetRepository:
    """Own transactional writes and explicit public feed projections."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tweet: Tweet) -> None:
        """Persist and commit one tweet before returning."""
        with self._session.begin():
            self._session.add(
                TweetModel(
                    public_id=tweet.id,
                    author_public_id=tweet.author_id,
                    text=tweet.text,
                    created_at=tweet.created_at,
                    updated_at=tweet.updated_at,
                    deleted_at=tweet.deleted_at,
                )
            )
            self._session.flush()

    def list_active(
        self, before: FeedCursor | None, limit: int
    ) -> tuple[PublicTweet, ...]:
        """Return one joined, active-only descending public projection."""
        statement = (
            select(
                TweetModel.public_id,
                TweetModel.text,
                TweetModel.created_at,
                UserModel.public_id.label("author_id"),
                UserModel.username,
                UserModel.display_name,
            )
            .join(UserModel, UserModel.public_id == TweetModel.author_public_id)
            .where(TweetModel.deleted_at.is_(None))
        )
        if before is not None:
            statement = statement.where(
                tuple_(TweetModel.created_at, TweetModel.public_id)
                < tuple_(before.created_at, before.tweet_id)
            )
        statement = statement.order_by(
            TweetModel.created_at.desc(), TweetModel.public_id.desc()
        ).limit(limit)

        with self._session.begin():
            rows = self._session.execute(statement).all()
        return tuple(
            PublicTweet(
                id=row.public_id,
                text=row.text,
                created_at=row.created_at,
                author=PublicAuthorSummary(
                    id=row.author_id,
                    username=row.username,
                    display_name=row.display_name,
                ),
            )
            for row in rows
        )

    def soft_delete(
        self, tweet_id: UUID, requester_id: UUID, deleted_at: datetime
    ) -> DeleteOutcome:
        """Classify, lock, and mutate an active tweet in one transaction."""
        with self._session.begin():
            row = self._session.execute(
                select(TweetModel)
                .where(
                    TweetModel.public_id == tweet_id,
                    TweetModel.deleted_at.is_(None),
                )
                .with_for_update()
            ).scalar_one_or_none()
            if row is None:
                return DeleteOutcome.NOT_FOUND
            if row.author_public_id != requester_id:
                return DeleteOutcome.FORBIDDEN
            row.deleted_at = deleted_at
            row.updated_at = deleted_at
            self._session.flush()
            return DeleteOutcome.DELETED
