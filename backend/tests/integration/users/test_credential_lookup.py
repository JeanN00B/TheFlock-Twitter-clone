"""Users PostgreSQL credential lookup seam."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; PostgreSQL integration test skipped",
        allow_module_level=True,
    )

from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.orm import Session

from app.users.application.credential_lookup import UserCredential
from app.users.domain.user import NewUser
from app.users.infrastructure.credential_lookup import SQLAlchemyUserCredentialLookup
from app.users.infrastructure.user_model import UserModel
from app.users.infrastructure.user_repository import SQLAlchemyUserRepository


PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$somesalt$somehashvalue"
FIXED_INSTANT = datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone.utc)


def _new_user(**overrides) -> NewUser:
    values = {
        "public_id": uuid4(),
        "email": "person@example.com",
        "username": "alice_42",
        "display_name": "Alice Example",
        "password_hash": PASSWORD_HASH,
        "created_at": FIXED_INSTANT,
        "updated_at": FIXED_INSTANT,
    }
    values.update(overrides)
    return NewUser(**values)


@pytest.fixture()
def db_session():
    engine = create_engine(TEST_DATABASE_URL)
    session = Session(engine)
    session.execute(delete(UserModel))
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(delete(UserModel))
        session.commit()
        session.close()
        engine.dispose()


def test_lookup_returns_only_the_credential_projection_and_requires_canonical_email(
    db_session: Session,
) -> None:
    user = _new_user(email="person+tag@example.com", username="plus_user")
    SQLAlchemyUserRepository(db_session).add(user)

    lookup = SQLAlchemyUserCredentialLookup(db_session)
    hit = lookup.find_by_canonical_email("person+tag@example.com")
    miss = lookup.find_by_canonical_email(" Person+tag@Example.COM ")

    assert type(hit) is UserCredential
    assert hit.public_id == user.public_id
    assert hit.password_hash == PASSWORD_HASH
    assert not hasattr(hit, "id")
    assert not hasattr(hit, "email")
    assert not hasattr(hit, "username")
    assert not hasattr(hit, "internal_id")
    assert miss is None


def test_lookup_misses_a_distinct_canonical_email_without_normalizing_it(
    db_session: Session,
) -> None:
    user = _new_user(email="person@example.com")
    SQLAlchemyUserRepository(db_session).add(user)

    missing = SQLAlchemyUserCredentialLookup(db_session).find_by_canonical_email(
        "nobody@example.com"
    )

    assert missing is None
    assert not db_session.in_transaction()


def test_lookup_selects_only_public_id_and_password_hash(db_session: Session) -> None:
    user = _new_user()
    SQLAlchemyUserRepository(db_session).add(user)
    statements: list[str] = []

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def capture_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    credential = SQLAlchemyUserCredentialLookup(db_session).find_by_canonical_email(user.email)

    normalized_selects = [" ".join(statement.lower().split()) for statement in statements]
    normalized_selects = [
        statement for statement in normalized_selects if " from users " in f" {statement} "
    ]
    assert any(
        "select users.public_id, users.password_hash from users" in statement
        for statement in normalized_selects
    )
    selected_columns = [statement.split(" from users ", 1)[0] for statement in normalized_selects]
    assert all("users.id" not in statement for statement in selected_columns)
    assert all("users.email" not in statement for statement in selected_columns)
    assert all("users.username" not in statement for statement in selected_columns)
    assert credential is not None


def test_lookup_ends_read_transaction_before_same_session_registration_write(
    db_session: Session,
) -> None:
    user = _new_user()
    SQLAlchemyUserRepository(db_session).add(user)

    credential = SQLAlchemyUserCredentialLookup(db_session).find_by_canonical_email(user.email)
    assert credential is not None
    assert not db_session.in_transaction()

    SQLAlchemyUserRepository(db_session).add(
        _new_user(
            email="second@example.com",
            username="second_user",
        )
    )

    assert db_session.execute(select(func.count()).select_from(UserModel)).scalar_one() == 2
