"""SQLAlchemy persistence model for tweets."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class TweetModel(Base):
    """PostgreSQL row for one original tweet."""

    __tablename__ = "tweets"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tweets_id"),
        UniqueConstraint("public_id", name="uq_tweets_public_id"),
        ForeignKeyConstraint(
            ["author_public_id"],
            ["users.public_id"],
            name="fk_tweets_author_public_id_users",
            ondelete="RESTRICT",
        ),
        CheckConstraint("char_length(text) > 0", name="ck_tweets_text_nonempty"),
        CheckConstraint("char_length(text) <= 280", name="ck_tweets_text_max_280"),
        CheckConstraint(
            "updated_at >= created_at AND "
            "(deleted_at IS NULL OR "
            "(deleted_at >= created_at AND updated_at >= deleted_at))",
            name="ck_tweets_timestamp_order",
        ),
        Index(
            "ix_tweets_active_timeline_created_at_public_id_desc",
            text("created_at DESC"),
            text("public_id DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_tweets_active_author_timeline_created_at_public_id_desc",
            "author_public_id",
            text("created_at DESC"),
            text("public_id DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    public_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    author_public_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    text: Mapped[str] = mapped_column(String(280), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
