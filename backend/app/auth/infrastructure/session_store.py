"""Durable transaction-owning adapter for Auth sessions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as SQLAlchemySession

from app.auth.domain.session import Session, SessionTokenDigest

from .session_model import SessionModel


class SQLAlchemySessionStore:
    """Persist one domain session and acknowledge it only after commit."""

    def __init__(self, session: SQLAlchemySession) -> None:
        self._session = session

    def add_committed(self, session: Session) -> None:
        """Insert and flush inside a transaction whose commit is acknowledged."""

        row = SessionModel(
            token_hash=session.token_digest.value,
            user_public_id=session.user_public_id,
            issued_at=session.issued_at,
            expires_at=session.expires_at,
        )
        with self._session.begin():
            self._session.add(row)
            self._session.flush()

    def find_active_user(
        self, token_digest: SessionTokenDigest, now: datetime
    ) -> UUID | None:
        """Return the user ID for a digest whose session has not expired."""

        with self._session.begin():
            return self._session.execute(
                select(SessionModel.user_public_id).where(
                    SessionModel.token_hash == token_digest.value,
                    SessionModel.expires_at > now,
                )
            ).scalar_one_or_none()

    def revoke(self, token_digest: SessionTokenDigest) -> None:
        """Delete a matching session inside an idempotent transaction."""

        with self._session.begin():
            self._session.execute(
                delete(SessionModel).where(
                    SessionModel.token_hash == token_digest.value
                )
            )
