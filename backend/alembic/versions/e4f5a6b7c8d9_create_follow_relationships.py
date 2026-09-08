"""Create directed follow relationships.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4f5a6b7c8d9"
down_revision: str | Sequence[str] | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follow_relationships",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("follower_public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("followed_public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_follow_relationships_id"),
        sa.UniqueConstraint("follower_public_id", "followed_public_id", name="uq_follow_relationships_follower_followed"),
        sa.CheckConstraint("follower_public_id <> followed_public_id", name="ck_follow_relationships_not_self"),
        sa.ForeignKeyConstraint(["follower_public_id"], ["users.public_id"], name="fk_follow_relationships_follower_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["followed_public_id"], ["users.public_id"], name="fk_follow_relationships_followed_users", ondelete="RESTRICT"),
    )
    op.create_index("ix_follow_relationships_followed_follower", "follow_relationships", ["followed_public_id", "follower_public_id"], unique=False)


def downgrade() -> None:
    op.drop_table("follow_relationships")
