"""Create digest-only Auth sessions.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the additive sessions table and its lookup indexes."""

    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "user_public_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("token_hash", name="pk_sessions"),
        sa.ForeignKeyConstraint(
            ["user_public_id"],
            ["users.public_id"],
            name="fk_sessions_user_public_id_users_public_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32",
            name="ck_sessions_token_hash_32_bytes",
        ),
        sa.CheckConstraint(
            "expires_at > issued_at",
            name="ck_sessions_expires_after_issued",
        ),
    )
    op.create_index(
        "ix_sessions_user_public_id", "sessions", ["user_public_id"]
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])


def downgrade() -> None:
    """Drop only the sessions table and its indexes."""

    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_public_id", table_name="sessions")
    op.drop_table("sessions")
