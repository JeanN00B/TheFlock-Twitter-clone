"""Users PostgreSQL persistence seam: schema, migration, repository."""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; PostgreSQL integration test skipped",
        allow_module_level=True,
    )

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.infrastructure.database import Base


def test_users_table_is_registered_with_expected_name() -> None:
    from app.users.infrastructure.user_model import UserModel  # noqa: F401

    assert "users" in Base.metadata.tables
    assert Base.metadata.tables["users"] is UserModel.__table__


def test_users_table_has_required_columns_and_types() -> None:
    from app.users.infrastructure import user_model  # noqa: F401

    table = Base.metadata.tables["users"]
    assert isinstance(table.c["id"].type, BigInteger)
    assert table.c["id"].primary_key
    assert isinstance(table.c["public_id"].type, PG_UUID)
    assert isinstance(table.c["email"].type, String)
    assert table.c["email"].type.length == 254
    assert isinstance(table.c["username"].type, String)
    assert table.c["username"].type.length == 15
    assert isinstance(table.c["display_name"].type, String)
    assert table.c["display_name"].type.length == 50
    assert isinstance(table.c["password_hash"].type, Text)
    assert isinstance(table.c["created_at"].type, DateTime)
    assert table.c["created_at"].type.timezone is True
    assert isinstance(table.c["updated_at"].type, DateTime)
    assert table.c["updated_at"].type.timezone is True


def test_users_table_enforces_identity_and_required_fields() -> None:
    from app.users.infrastructure import user_model  # noqa: F401

    table = Base.metadata.tables["users"]
    assert table.c["id"].identity is not None
    for column in (
        "id",
        "public_id",
        "email",
        "username",
        "display_name",
        "password_hash",
        "created_at",
        "updated_at",
    ):
        assert table.c[column].nullable is False, column


def test_users_table_has_named_uniqueness_constraints() -> None:
    from app.users.infrastructure import user_model  # noqa: F401

    table = Base.metadata.tables["users"]
    names = {
        constraint.name
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert names == {"uq_users_public_id", "uq_users_email", "uq_users_username"}


def test_alembic_env_imports_user_model_metadata() -> None:
    env_source = Path("alembic/env.py").read_text(encoding="utf-8")
    assert "app.users.infrastructure.user_model" in env_source
    assert "Base.metadata" in env_source


def test_first_migration_creates_only_users_table() -> None:
    versions = sorted(Path("alembic/versions").glob("*_create_users.py"))
    assert len(versions) == 1
    source = versions[0].read_text(encoding="utf-8")
    assert "create_table" in source
    assert "'users'" in source or '"users"' in source
    assert "uq_users_public_id" in source
    assert "uq_users_email" in source
    assert "uq_users_username" in source
    assert "drop_table" in source


# --- Repository seam (WU3-RED-2) ---

from sqlalchemy import create_engine, delete, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.users.application.register_user import UserWriteConflict  # noqa: E402
from app.users.domain.user import NewUser, PublicUser  # noqa: E402
from app.auth.infrastructure.session_model import SessionModel  # noqa: E402
from app.users.infrastructure.public_user_lookup import (  # noqa: E402
    SQLAlchemyPublicUserLookup,
)
from app.users.infrastructure.user_model import UserModel  # noqa: E402
from app.users.infrastructure.user_repository import SQLAlchemyUserRepository  # noqa: E402

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


def test_repository_persists_user_with_generated_bigint_id(db_session: Session) -> None:
    repository = SQLAlchemyUserRepository(db_session)
    user = _new_user()

    repository.add(user)

    row = db_session.execute(select(UserModel).where(UserModel.email == user.email)).scalar_one()
    assert isinstance(row.id, int)
    assert row.public_id == user.public_id
    assert row.email == "person@example.com"
    assert row.username == "alice_42"
    assert row.display_name == "Alice Example"
    assert row.password_hash == PASSWORD_HASH
    assert row.created_at == FIXED_INSTANT
    assert row.updated_at == FIXED_INSTANT


def test_repository_keeps_username_and_display_name_independent(db_session: Session) -> None:
    repository = SQLAlchemyUserRepository(db_session)
    user = _new_user(username="alice_42", display_name="Ada Lovelace")

    repository.add(user)

    row = db_session.execute(select(UserModel).where(UserModel.public_id == user.public_id)).scalar_one()
    assert row.username == "alice_42"
    assert row.display_name == "Ada Lovelace"
    assert row.username != row.display_name


def test_repository_conflict_on_duplicate_email(db_session: Session) -> None:
    repository = SQLAlchemyUserRepository(db_session)
    repository.add(_new_user(email="person@example.com", username="alice_42"))

    with pytest.raises(UserWriteConflict) as error:
        repository.add(_new_user(email=" PERSON@example.com ".strip().lower(), username="other_user"))

    assert error.value.fields == frozenset({"email"})
    assert db_session.execute(select(func.count()).select_from(UserModel)).scalar_one() == 1


def test_repository_conflict_on_duplicate_username(db_session: Session) -> None:
    repository = SQLAlchemyUserRepository(db_session)
    repository.add(_new_user(email="person@example.com", username="alice_42"))

    with pytest.raises(UserWriteConflict) as error:
        repository.add(_new_user(email="other@example.com", username="alice_42"))

    assert error.value.fields == frozenset({"username"})
    assert db_session.execute(select(func.count()).select_from(UserModel)).scalar_one() == 1


def test_repository_conflict_reports_both_fields_when_both_exist(db_session: Session) -> None:
    repository = SQLAlchemyUserRepository(db_session)
    repository.add(_new_user(email="first@example.com", username="first_user"))
    repository.add(_new_user(email="second@example.com", username="second_user"))

    with pytest.raises(UserWriteConflict) as error:
        repository.add(_new_user(email="first@example.com", username="second_user"))

    assert error.value.fields == frozenset({"email", "username"})
    assert db_session.execute(select(func.count()).select_from(UserModel)).scalar_one() == 2


def test_repository_does_not_close_session(db_session: Session) -> None:
    repository = SQLAlchemyUserRepository(db_session)

    repository.add(_new_user(email="first@example.com", username="first_user"))
    repository.add(_new_user(email="second@example.com", username="second_user"))

    assert db_session.execute(select(func.count()).select_from(UserModel)).scalar_one() == 2


def test_public_user_lookup_returns_credential_free_projection_or_none(
    db_session: Session,
) -> None:
    user = _new_user()
    SQLAlchemyUserRepository(db_session).add(user)

    lookup = SQLAlchemyPublicUserLookup(db_session)
    public_user = lookup.find_by_public_id(user.public_id)

    assert isinstance(public_user, PublicUser)
    assert public_user.id == user.public_id
    assert public_user.email == user.email
    assert public_user.username == user.username
    assert public_user.display_name == user.display_name
    assert public_user.created_at == FIXED_INSTANT
    assert public_user.updated_at == FIXED_INSTANT
    assert not hasattr(public_user, "password_hash")
    assert lookup.find_by_public_id(uuid4()) is None


# --- Race, rollback, migration lifecycle (WU3-RED-3) ---

import threading  # noqa: E402

from alembic import command as alembic_command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from sqlalchemy import inspect as sa_inspect  # noqa: E402


def _alembic_config() -> AlembicConfig:
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


def test_concurrent_duplicate_registration_is_race_safe() -> None:
    cleanup_engine = create_engine(TEST_DATABASE_URL)
    with Session(cleanup_engine) as cleanup:
        cleanup.execute(delete(SessionModel))
        cleanup.execute(delete(UserModel))
        cleanup.commit()
    cleanup_engine.dispose()

    barrier = threading.Barrier(2)
    outcomes: dict[str, str | frozenset] = {}

    def attempt(name: str) -> None:
        engine = create_engine(TEST_DATABASE_URL)
        session = Session(engine)
        try:
            barrier.wait(timeout=10)
            SQLAlchemyUserRepository(session).add(_new_user())
            outcomes[name] = "committed"
        except UserWriteConflict as error:
            outcomes[name] = error.fields
        finally:
            session.close()
            engine.dispose()

    first = threading.Thread(target=attempt, args=("first",))
    second = threading.Thread(target=attempt, args=("second",))
    first.start()
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)

    assert set(outcomes) == {"first", "second"}
    committed = [name for name, outcome in outcomes.items() if outcome == "committed"]
    conflicts = [outcome for outcome in outcomes.values() if outcome != "committed"]
    assert len(committed) == 1
    assert len(conflicts) == 1
    assert isinstance(conflicts[0], frozenset)
    assert conflicts[0] and conflicts[0] <= frozenset({"email", "username"})

    verify_engine = create_engine(TEST_DATABASE_URL)
    try:
        with Session(verify_engine) as verify:
            assert verify.execute(select(func.count()).select_from(UserModel)).scalar_one() == 1
            verify.execute(delete(SessionModel))
            verify.execute(delete(UserModel))
            verify.commit()
    finally:
        verify_engine.dispose()


def test_failed_registration_is_atomic_and_session_remains_usable(db_session: Session) -> None:
    repository = SQLAlchemyUserRepository(db_session)
    repository.add(_new_user(email="person@example.com", username="alice_42"))

    with pytest.raises(UserWriteConflict):
        repository.add(_new_user(email="person@example.com", username="other_user"))

    repository.add(_new_user(email="other@example.com", username="other_user"))
    assert db_session.execute(select(func.count()).select_from(UserModel)).scalar_one() == 2


def test_unknown_public_id_collision_is_unexpected_failure(db_session: Session) -> None:
    repository = SQLAlchemyUserRepository(db_session)
    first = _new_user()
    repository.add(first)

    with pytest.raises(Exception) as error:
        repository.add(_new_user(public_id=first.public_id, email="other@example.com", username="other_user"))

    assert not isinstance(error.value, UserWriteConflict)
    assert db_session.execute(select(func.count()).select_from(UserModel)).scalar_one() == 1


def test_migration_lifecycle_drops_and_recreates_only_users(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.settings import get_settings
    from app.infrastructure.database import get_engine, get_session_factory

    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    config = _alembic_config()
    cleanup_engine = create_engine(TEST_DATABASE_URL)
    try:
        with Session(cleanup_engine) as cleanup:
            cleanup.execute(delete(SessionModel))
            cleanup.execute(delete(UserModel))
            cleanup.commit()
    finally:
        cleanup_engine.dispose()

    alembic_command.downgrade(config, "b1c2d3e4f5a6")
    try:
        engine = create_engine(TEST_DATABASE_URL)
        try:
            table_names = set(sa_inspect(engine).get_table_names())
            assert "users" in table_names
            assert "sessions" not in table_names
        finally:
            engine.dispose()
    finally:
        alembic_command.upgrade(config, "head")

    engine = create_engine(TEST_DATABASE_URL)
    try:
        inspector = sa_inspect(engine)
        assert {"users", "sessions"} <= set(inspector.get_table_names())
        assert {constraint["name"] for constraint in inspector.get_unique_constraints("users")} == {
            "uq_users_public_id",
            "uq_users_email",
            "uq_users_username",
        }
        with Session(engine) as session:
            session.execute(delete(SessionModel))
            session.execute(delete(UserModel))
            session.commit()
    finally:
        engine.dispose()


# --- Triangulation: canonical persistence and live schema contract ---

from sqlalchemy import text as sa_text  # noqa: E402


def test_repository_preserves_plus_tag_email_verbatim(db_session: Session) -> None:
    repository = SQLAlchemyUserRepository(db_session)
    user = _new_user(email="person+tag@example.com", username="plus_user")

    repository.add(user)

    row = db_session.execute(select(UserModel).where(UserModel.public_id == user.public_id)).scalar_one()
    assert row.email == "person+tag@example.com"


def test_live_schema_matches_model_contract() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            columns = connection.execute(
                sa_text(
                    "SELECT column_name, data_type, is_nullable, is_identity "
                    "FROM information_schema.columns WHERE table_name='users'"
                )
            ).all()
            by_name = {row[0]: row for row in columns}
            assert by_name["id"][1] == "bigint"
            assert by_name["id"][3] == "YES"
            assert by_name["public_id"][1] == "uuid"
            assert by_name["created_at"][1] == "timestamp with time zone"
            assert by_name["updated_at"][1] == "timestamp with time zone"
            assert all(row[2] == "NO" for row in columns)
            constraints = connection.execute(
                sa_text("SELECT conname FROM pg_constraint WHERE conrelid='users'::regclass")
            ).all()
            names = {row[0] for row in constraints}
            assert {"uq_users_public_id", "uq_users_email", "uq_users_username"} <= names
    finally:
        engine.dispose()

