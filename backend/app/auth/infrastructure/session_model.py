"""SQLAlchemy persistence mapping for digest-only Auth sessions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class SessionModel(Base):
    """PostgreSQL row containing only a session digest and its lifetime."""

    __tablename__ = "sessions"
    __table_args__ = (
        PrimaryKeyConstraint("token_hash", name="pk_sessions"),
        CheckConstraint(
            "octet_length(token_hash) = 32",
            name="ck_sessions_token_hash_32_bytes",
        ),
        CheckConstraint(
            "expires_at > issued_at",
            name="ck_sessions_expires_after_issued",
        ),
        Index("ix_sessions_user_public_id", "user_public_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    user_public_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "users.public_id",
            name="fk_sessions_user_public_id_users_public_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
