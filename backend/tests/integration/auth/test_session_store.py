"""PostgreSQL schema and durable-store seam for opaque Auth sessions."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; PostgreSQL integration test skipped",
        allow_module_level=True,
    )

from alembic import command as alembic_command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from sqlalchemy import (  # noqa: E402
    DateTime,
    ForeignKeyConstraint,
    LargeBinary,
    PrimaryKeyConstraint,
    create_engine,
    delete,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.dialects.postgresql import UUID as PG_UUID  # noqa: E402
from sqlalchemy.orm import Session as SQLAlchemySession  # noqa: E402

from app.auth.domain.session import Session, SessionTokenDigest  # noqa: E402
from app.auth.infrastructure.session_model import SessionModel  # noqa: E402
from app.auth.infrastructure.session_store import SQLAlchemySessionStore  # noqa: E402
from app.infrastructure.database import Base  # noqa: E402
from app.users.infrastructure.user_model import UserModel  # noqa: E402


def _alembic_config() -> AlembicConfig:
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    try:
        alembic_command.upgrade(_alembic_config(), "head")
    finally:
        patch.undo()
    yield
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with SQLAlchemySession(engine) as cleanup:
            cleanup.execute(delete(SessionModel))
            cleanup.execute(delete(UserModel))
            cleanup.commit()
    finally:
        engine.dispose()


FIXED_ISSUED_AT = datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone.utc)
FIXED_EXPIRES_AT = FIXED_ISSUED_AT + timedelta(days=7)


def _domain_session(*, user_public_id=None, digest=b"d" * 32, issued_at=FIXED_ISSUED_AT):
    return Session(
        user_public_id=user_public_id or uuid4(),
        token_digest=SessionTokenDigest(digest),
        issued_at=issued_at,
        expires_at=issued_at + timedelta(days=7),
    )


def _seed_user(db_session: SQLAlchemySession, *, public_id=None) -> UUID:
    user_public_id = public_id or uuid4()
    db_session.add(
        UserModel(
            public_id=user_public_id,
            email=f"{user_public_id.hex[:12]}@example.com",
            username=f"u_{user_public_id.hex[:10]}",
            display_name="Session User",
            password_hash="encoded",
            created_at=FIXED_ISSUED_AT,
            updated_at=FIXED_ISSUED_AT,
        )
    )
    db_session.commit()
    return user_public_id


@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL)
    session = SQLAlchemySession(engine)
    session.execute(delete(SessionModel))
    session.execute(delete(UserModel))
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(delete(SessionModel))
        session.execute(delete(UserModel))
        session.commit()
        session.close()
        engine.dispose()


def test_session_model_declares_digest_only_schema() -> None:
    table = SessionModel.__table__

    assert table.name == "sessions"
    assert set(table.columns.keys()) == {
        "token_hash",
        "user_public_id",
        "issued_at",
        "expires_at",
    }
    assert isinstance(table.c.token_hash.type, LargeBinary)
    assert table.c.token_hash.type.length == 32
    assert isinstance(table.c.user_public_id.type, PG_UUID)
    assert isinstance(table.c.issued_at.type, DateTime)
    assert table.c.issued_at.type.timezone is True
    assert isinstance(table.c.expires_at.type, DateTime)
    assert table.c.expires_at.type.timezone is True
    assert all(column.nullable is False for column in table.columns)

    primary_keys = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, PrimaryKeyConstraint)
    ]
    assert [constraint.name for constraint in primary_keys] == ["pk_sessions"]
    assert {
        constraint.name
        for constraint in table.constraints
        if constraint.name and constraint.name.startswith("ck_sessions_")
    } == {
        "ck_sessions_token_hash_32_bytes",
        "ck_sessions_expires_after_issued",
    }
    foreign_keys = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]
    assert [constraint.name for constraint in foreign_keys] == [
        "fk_sessions_user_public_id_users_public_id"
    ]
    assert foreign_keys[0].ondelete == "CASCADE"
    assert {index.name for index in table.indexes} == {
        "ix_sessions_user_public_id",
        "ix_sessions_expires_at",
    }


def test_sessions_live_schema_has_named_constraints_indexes_and_fk() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    try:
        inspector = inspect(engine)
        columns = {
            column["name"]: column
            for column in inspector.get_columns("sessions")
        }
        assert set(columns) == {
            "token_hash",
            "user_public_id",
            "issued_at",
            "expires_at",
        }
        assert columns["token_hash"]["type"].__class__.__name__ == "BYTEA"
        assert columns["token_hash"]["nullable"] is False
        assert columns["user_public_id"]["type"].__class__ is PG_UUID
        assert all(column["nullable"] is False for column in columns.values())
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT format_type(a.atttypid, a.atttypmod) "
                    "FROM pg_attribute AS a "
                    "WHERE a.attrelid = 'sessions'::regclass "
                    "AND a.attname = 'token_hash'"
                )
            ).scalar_one() == "bytea"
        assert inspector.get_pk_constraint("sessions")["name"] == "pk_sessions"
        assert {
            check["name"] for check in inspector.get_check_constraints("sessions")
        } == {
            "ck_sessions_token_hash_32_bytes",
            "ck_sessions_expires_after_issued",
        }
        foreign_keys = inspector.get_foreign_keys("sessions")
        assert [foreign_key["name"] for foreign_key in foreign_keys] == [
            "fk_sessions_user_public_id_users_public_id"
        ]
        assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
        assert {
            index["name"] for index in inspector.get_indexes("sessions")
        } == {"ix_sessions_user_public_id", "ix_sessions_expires_at"}
    finally:
        engine.dispose()


def test_sessions_migration_declares_additive_upgrade_and_safe_downgrade() -> None:
    source = Path("alembic/versions/c2d3e4f5a6b7_create_sessions.py").read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "c2d3e4f5a6b7"' in source
    assert 'down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"' in source
    assert '"sessions"' in source
    assert '"pk_sessions"' in source
    assert '"fk_sessions_user_public_id_users_public_id"' in source
    assert '"ck_sessions_token_hash_32_bytes"' in source
    assert '"ck_sessions_expires_after_issued"' in source
    assert '"ix_sessions_user_public_id"' in source
    assert '"ix_sessions_expires_at"' in source
    assert '"users.public_id"' in source
    assert "drop_table" in source


def test_session_store_commits_and_is_visible_to_another_session(
    db_session: SQLAlchemySession,
) -> None:
    user_public_id = _seed_user(db_session)
    session = _domain_session(user_public_id=user_public_id)
    engine = db_session.get_bind()
    assert engine is not None

    SQLAlchemySessionStore(db_session).add_committed(session)
    with SQLAlchemySession(engine) as reader:
        row = reader.execute(
            select(SessionModel).where(
                SessionModel.token_hash == session.token_digest.value
            )
        ).scalar_one()
        assert row.user_public_id == user_public_id
        assert row.token_hash == b"d" * 32
        assert row.issued_at == FIXED_ISSUED_AT
        assert row.expires_at == FIXED_EXPIRES_AT
        assert row.issued_at.tzinfo is not None
        assert row.issued_at.utcoffset() == timedelta(0)
        assert reader.execute(
            text("SELECT octet_length(token_hash) FROM sessions")
        ).scalar_one() == 32


def test_two_sessions_share_user_without_replacement(
    db_session: SQLAlchemySession,
) -> None:
    user_public_id = _seed_user(db_session)
    first = _domain_session(user_public_id=user_public_id, digest=b"a" * 32)
    second = _domain_session(user_public_id=user_public_id, digest=b"b" * 32)
    store = SQLAlchemySessionStore(db_session)

    store.add_committed(first)
    store.add_committed(second)

    rows = db_session.execute(
        select(SessionModel).order_by(SessionModel.token_hash)
    ).scalars().all()
    assert len(rows) == 2
    assert {row.user_public_id for row in rows} == {user_public_id}
    assert {row.token_hash for row in rows} == {b"a" * 32, b"b" * 32}
    assert db_session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 2


def test_invalid_domain_digest_and_expiry_are_rejected() -> None:
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        SessionTokenDigest(b"x" * 31)
    with pytest.raises(ValueError, match="exactly seven days"):
        Session(
            user_public_id=uuid4(),
            token_digest=SessionTokenDigest(b"x" * 32),
            issued_at=FIXED_ISSUED_AT,
            expires_at=FIXED_ISSUED_AT,
        )


def test_database_checks_reject_invalid_digest_and_expiry_and_reuses_session(
    db_session: SQLAlchemySession,
) -> None:
    user_public_id = _seed_user(db_session)
    invalid_rows = (
        SessionModel(
            token_hash=b"x" * 31,
            user_public_id=user_public_id,
            issued_at=FIXED_ISSUED_AT,
            expires_at=FIXED_EXPIRES_AT,
        ),
        SessionModel(
            token_hash=b"y" * 32,
            user_public_id=user_public_id,
            issued_at=FIXED_ISSUED_AT,
            expires_at=FIXED_ISSUED_AT,
        ),
    )
    for invalid_row in invalid_rows:
        db_session.add(invalid_row)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    SQLAlchemySessionStore(db_session).add_committed(
        _domain_session(user_public_id=user_public_id, digest=b"v" * 32)
    )
    assert db_session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 1


def test_duplicate_commit_failure_rolls_back_and_store_session_is_reusable(
    db_session: SQLAlchemySession,
) -> None:
    user_public_id = _seed_user(db_session)
    store = SQLAlchemySessionStore(db_session)
    store.add_committed(
        _domain_session(user_public_id=user_public_id, digest=b"d" * 32)
    )

    with pytest.raises(IntegrityError):
        store.add_committed(
            _domain_session(user_public_id=user_public_id, digest=b"d" * 32)
        )

    store.add_committed(
        _domain_session(user_public_id=user_public_id, digest=b"e" * 32)
    )
    assert db_session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 2


def test_foreign_key_rejects_unknown_user_and_cascades_on_delete(
    db_session: SQLAlchemySession,
) -> None:
    known_user = _seed_user(db_session)
    store = SQLAlchemySessionStore(db_session)
    with pytest.raises(IntegrityError):
        store.add_committed(_domain_session(user_public_id=uuid4()))

    store.add_committed(_domain_session(user_public_id=known_user, digest=b"f" * 32))
    db_session.execute(delete(UserModel).where(UserModel.public_id == known_user))
    db_session.commit()
    assert db_session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 0


def test_migration_downgrade_keeps_users_and_upgrade_restores_sessions() -> None:
    config = _alembic_config()
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with SQLAlchemySession(engine) as cleanup:
            cleanup.execute(delete(SessionModel))
            cleanup.execute(delete(UserModel))
            cleanup.commit()
        alembic_command.downgrade(config, "b1c2d3e4f5a6")
        try:
            names = inspect(engine).get_table_names()
            assert "users" in names
            assert "sessions" not in names
        finally:
            alembic_command.upgrade(config, "head")
        names = inspect(engine).get_table_names()
        assert {"users", "sessions"} <= set(names)
    finally:
        engine.dispose()
