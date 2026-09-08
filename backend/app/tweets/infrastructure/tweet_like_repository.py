"""SQLAlchemy adapter for atomic tweet-like state mutations."""

from uuid import UUID

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.tweets.domain.tweet import LikeState
from app.tweets.infrastructure.tweet_like_model import TweetLikeModel
from app.tweets.infrastructure.tweet_model import TweetModel


class SQLAlchemyTweetLikeRepository:
    """Persist one actor's requested like state and return committed state."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def set_state(self, tweet_id: UUID, actor_id: UUID, liked: bool) -> LikeState | None:
        state: LikeState | None = None
        try:
            with self._session.begin():
                target = self._session.execute(
                    select(TweetModel.public_id)
                    .where(
                        TweetModel.public_id == tweet_id,
                        TweetModel.deleted_at.is_(None),
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if target is not None:
                    if liked:
                        self._session.execute(
                            insert(TweetLikeModel)
                            .values(
                                tweet_public_id=tweet_id,
                                actor_public_id=actor_id,
                            )
                            .on_conflict_do_nothing(constraint="pk_tweet_likes")
                        )
                    else:
                        self._session.execute(
                            delete(TweetLikeModel).where(
                                TweetLikeModel.tweet_public_id == tweet_id,
                                TweetLikeModel.actor_public_id == actor_id,
                            )
                        )

                    count, actor_state = self._session.execute(
                        select(
                            func.count(TweetLikeModel.actor_public_id),
                            exists(
                                select(TweetLikeModel.actor_public_id).where(
                                    TweetLikeModel.tweet_public_id == tweet_id,
                                    TweetLikeModel.actor_public_id == actor_id,
                                )
                            ),
                        ).where(TweetLikeModel.tweet_public_id == tweet_id)
                    ).one()
                    if actor_state is not liked:
                        raise RuntimeError("like projection disagrees with requested state")
                    state = LikeState(
                        tweet_id=tweet_id,
                        like_count=count,
                        liked_by_actor=actor_state,
                    )
        except Exception:
            self._session.rollback()
            raise
        return state
