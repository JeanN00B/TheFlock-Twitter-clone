"""Add directional relationship-list indexes."""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: str | Sequence[str] | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_follow_relationships_followed_created_at_follower_desc", "follow_relationships", ["followed_public_id", sa.text("created_at DESC"), sa.text("follower_public_id DESC")])
    op.create_index("ix_follow_relationships_follower_created_at_followed_desc", "follow_relationships", ["follower_public_id", sa.text("created_at DESC"), sa.text("followed_public_id DESC")])


def downgrade() -> None:
    op.drop_index("ix_follow_relationships_follower_created_at_followed_desc", table_name="follow_relationships")
    op.drop_index("ix_follow_relationships_followed_created_at_follower_desc", table_name="follow_relationships")
