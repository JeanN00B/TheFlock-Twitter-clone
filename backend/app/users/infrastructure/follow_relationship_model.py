"""SQLAlchemy model for directed follow relationships."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, Identity, Index, PrimaryKeyConstraint, desc, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class FollowRelationshipModel(Base):
    __tablename__ = "follow_relationships"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_follow_relationships_id"),
        UniqueConstraint("follower_public_id", "followed_public_id", name="uq_follow_relationships_follower_followed"),
        CheckConstraint("follower_public_id <> followed_public_id", name="ck_follow_relationships_not_self"),
        ForeignKeyConstraint(["follower_public_id"], ["users.public_id"], name="fk_follow_relationships_follower_users", ondelete="RESTRICT"),
        ForeignKeyConstraint(["followed_public_id"], ["users.public_id"], name="fk_follow_relationships_followed_users", ondelete="RESTRICT"),
        Index("ix_follow_relationships_followed_follower", "followed_public_id", "follower_public_id"),
        Index("ix_follow_relationships_followed_created_at_follower_desc", "followed_public_id", desc("created_at"), desc("follower_public_id")),
        Index("ix_follow_relationships_follower_created_at_followed_desc", "follower_public_id", desc("created_at"), desc("followed_public_id")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity())
    follower_public_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    followed_public_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
