"""Durable transaction-owning adapter for Auth sessions."""

from sqlalchemy.orm import Session as SQLAlchemySession

from app.auth.domain.session import Session

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
