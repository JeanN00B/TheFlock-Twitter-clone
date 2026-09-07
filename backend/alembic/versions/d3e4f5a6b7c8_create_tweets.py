"""Create persisted original tweets.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the additive tweets table and active timeline index."""
    op.create_table(
        "tweets",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.String(length=280), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_tweets_id"),
        sa.UniqueConstraint("public_id", name="uq_tweets_public_id"),
        sa.ForeignKeyConstraint(
            ["author_public_id"], ["users.public_id"],
            name="fk_tweets_author_public_id_users", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("char_length(text) > 0", name="ck_tweets_text_nonempty"),
        sa.CheckConstraint("char_length(text) <= 280", name="ck_tweets_text_max_280"),
        sa.CheckConstraint(
            "updated_at >= created_at AND "
            "(deleted_at IS NULL OR "
            "(deleted_at >= created_at AND updated_at >= deleted_at))",
            name="ck_tweets_timestamp_order",
        ),
    )
    op.create_index(
        "ix_tweets_active_timeline_created_at_public_id_desc",
        "tweets",
        [sa.text("created_at DESC"), sa.text("public_id DESC")],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Remove only tweet persistence."""
    op.drop_index(
        "ix_tweets_active_timeline_created_at_public_id_desc", table_name="tweets"
    )
    op.drop_table("tweets")
