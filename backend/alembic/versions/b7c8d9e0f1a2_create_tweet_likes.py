"""Create tweet-like relationships.

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7c8d9e0f1a2"
down_revision: str | Sequence[str] | None = "a6b7c8d9e0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_tweet_likes_actor_public_id_tweet_public_id"


def upgrade() -> None:
    op.create_table(
        "tweet_likes",
        sa.Column("tweet_public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tweet_public_id", "actor_public_id", name="pk_tweet_likes"
        ),
        sa.ForeignKeyConstraint(
            ["tweet_public_id"],
            ["tweets.public_id"],
            name="fk_tweet_likes_tweet_public_id_tweets",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_public_id"],
            ["users.public_id"],
            name="fk_tweet_likes_actor_public_id_users",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        INDEX_NAME,
        "tweet_likes",
        ["actor_public_id", "tweet_public_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="tweet_likes")
    op.drop_table("tweet_likes")
