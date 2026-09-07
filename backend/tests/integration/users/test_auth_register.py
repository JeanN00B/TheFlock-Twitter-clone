"""Users registration HTTP seam."""

import os
from datetime import datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, StrictStr
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.infrastructure.database import get_engine, get_session_factory
from app.main import app, registration_request_validation_handler
from app.auth.infrastructure.session_model import SessionModel
from app.users.infrastructure.user_model import UserModel

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; PostgreSQL integration test skipped",
        allow_module_level=True,
    )


@pytest.fixture()
def clean_users(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    engine = create_engine(TEST_DATABASE_URL)
    with Session(engine) as session:
        session.execute(delete(SessionModel))
        session.execute(delete(UserModel))
        session.commit()
    try:
        yield engine
    finally:
        with Session(engine) as session:
            session.execute(delete(SessionModel))
            session.execute(delete(UserModel))
            session.commit()
        engine.dispose()
        get_settings.cache_clear()
        get_engine.cache_clear()
        get_session_factory.cache_clear()


def test_register_endpoint_creates_exact_public_user(clean_users) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            json={
                "email": "  Person+tag@Example.COM  ",
                "username": "  Alice_42  ",
                "display_name": "  Ada Lovelace  ",
                "password": "  exact password  ",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "username",
        "display_name",
        "email",
        "created_at",
        "updated_at",
    }
    assert UUID(body["id"]).version == 4
    assert body["username"] == "alice_42"
    assert body["display_name"] == "Ada Lovelace"
    assert body["email"] == "person+tag@example.com"
    assert body["created_at"].endswith("Z")
    assert body["updated_at"].endswith("Z")
    assert datetime.fromisoformat(body["created_at"].replace("Z", "+00:00")) == datetime.fromisoformat(
        body["updated_at"].replace("Z", "+00:00")
    )
    assert "Set-Cookie" not in response.headers
    assert "exact password" not in response.text
    assert "password_hash" not in body
    assert "internal_id" not in body

    with Session(clean_users) as session:
        assert session.execute(select(func.count()).select_from(UserModel)).scalar_one() == 1
        assert session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 0
        row = session.execute(select(UserModel)).scalar_one()
        assert row.email == "person+tag@example.com"
        assert row.username == "alice_42"
        assert row.display_name == "Ada Lovelace"
        assert row.password_hash.startswith("$argon2id$")
        assert "exact password" not in row.password_hash


def _post_registration(client: TestClient, **overrides):
    payload = {
        "email": "person@example.com",
        "username": "alice_42",
        "display_name": "Alice Example",
        "password": "valid password",
    }
    payload.update(overrides)
    return client.post("/auth/register", json=payload)


def test_register_maps_normalized_email_conflict(clean_users) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        assert _post_registration(client).status_code == 201
        response = _post_registration(
            client,
            email=" PERSON@EXAMPLE.COM ",
            username="other_user",
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "conflict", "fields": {"email": "already_exists"}}
    }
    assert "Set-Cookie" not in response.headers
    assert "person@example.com" not in response.text


def test_register_maps_canonical_username_conflict(clean_users) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        assert _post_registration(client).status_code == 201
        response = _post_registration(
            client,
            email="other@example.com",
            username=" Alice_42 ",
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "conflict", "fields": {"username": "already_exists"}}
    }
    assert "Set-Cookie" not in response.headers


def test_register_maps_both_conflicts_without_database_details(clean_users) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        assert _post_registration(client).status_code == 201
        assert _post_registration(
            client,
            email="second@example.com",
            username="second_user",
        ).status_code == 201
        response = _post_registration(
            client,
            email=" PERSON@EXAMPLE.COM ",
            username=" Second_User ",
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "conflict",
            "fields": {
                "email": "already_exists",
                "username": "already_exists",
            },
        }
    }
    assert "Set-Cookie" not in response.headers
    assert "uq_users" not in response.text


@pytest.mark.parametrize(
    ("payload", "expected_fields"),
    [
        ({"email": "person@example.com"}, {"username": "invalid", "display_name": "invalid", "password": "invalid"}),
        ({"email": "person@example.com", "username": "alice", "display_name": "Alice", "password": None}, {"password": "invalid"}),
        ({"email": "person@example.com", "username": 42, "display_name": "Alice", "password": "valid pass"}, {"username": "invalid"}),
        ({"email": "person@example.com", "username": "alice", "display_name": "Alice", "password": "valid pass", "unexpected": "value"}, {"unexpected": "invalid"}),
    ],
)
def test_register_maps_request_validation_to_stable_fields(payload, expected_fields, clean_users) -> None:
    with TestClient(app) as client:
        response = client.post("/auth/register", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "fields": expected_fields}
    }
    assert "valid pass" not in response.text
    assert "Set-Cookie" not in response.headers


@pytest.mark.parametrize("content", ["{", "null", "[]", '"text"'])
def test_register_maps_malformed_or_non_object_body_to_body_field(content: str, clean_users) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            content=content,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "fields": {"body": "invalid"}}
    }


def test_health_contract_remains_unchanged() -> None:
    with TestClient(app) as client:
        client.cookies.set("flock_session", "opaque-placeholder")
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("payload", "expected_fields"),
    [
        (
            {
                "email": "not-an-email",
                "username": "@alice",
                "display_name": "   ",
                "password": "short",
            },
            {
                "email": "invalid",
                "username": "invalid",
                "display_name": "invalid",
                "password": "invalid",
            },
        ),
        (
            {
                "email": "person@example.com",
                "username": "a" * 16,
                "display_name": "Alice",
                "password": "valid pass",
            },
            {"username": "invalid"},
        ),
        (
            {
                "email": "person@example.com",
                "username": "alice",
                "display_name": "x" * 51,
                "password": "valid pass",
            },
            {"display_name": "invalid"},
        ),
        (
            {
                "email": "person@example.com",
                "username": "alice",
                "display_name": "Alice",
                "password": "p" * 129,
            },
            {"password": "invalid"},
        ),
    ],
)
def test_register_maps_application_validation_without_persistence(
    payload, expected_fields, clean_users
) -> None:
    with TestClient(app) as client:
        response = client.post("/auth/register", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "fields": expected_fields}
    }
    assert payload["password"] not in response.text
    assert "Set-Cookie" not in response.headers
    with Session(clean_users) as session:
        assert session.execute(select(func.count()).select_from(UserModel)).scalar_one() == 0
        assert session.execute(select(func.count()).select_from(SessionModel)).scalar_one() == 0


class ValidationProbe(BaseModel):
    value: StrictStr


def test_validation_mapping_keeps_fastapi_stock_shape_elsewhere() -> None:
    probe_app = FastAPI()
    probe_app.add_exception_handler(
        RequestValidationError, registration_request_validation_handler
    )

    @probe_app.post("/probe")
    def probe(payload: ValidationProbe):
        return payload

    with TestClient(probe_app) as client:
        response = client.post("/probe", json={"value": 42})

    assert response.status_code == 422
    assert "detail" in response.json()
    assert response.json()["detail"][0]["type"] == "string_type"
    assert response.json()["detail"][0]["input"] == 42
