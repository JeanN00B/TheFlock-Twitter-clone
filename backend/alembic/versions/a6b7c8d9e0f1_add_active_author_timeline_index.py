"""Add active author timeline index.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a6b7c8d9e0f1"
down_revision: str | Sequence[str] | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_tweets_active_author_timeline_created_at_public_id_desc"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "tweets",
        ["author_public_id", sa.text("created_at DESC"), sa.text("public_id DESC")],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="tweets")
