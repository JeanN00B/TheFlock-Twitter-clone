from datetime import datetime, timezone
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.auth.application.login import (
    CommittedSessionCookie,
    InvalidCredentials,
    LoginCommand,
    LoginValidationError,
    RawSessionToken,
)
from app.auth.infrastructure import login_router as login_router_module
from app.auth.infrastructure.login_router import build_login_router
from app.main import registration_request_validation_handler


pytestmark = pytest.mark.unit


EXPIRES_AT = datetime(2026, 9, 13, 13, 10, 26, tzinfo=timezone.utc)
RAW_TOKEN = b"r" * 32


class FakeLogin:
    def __init__(self, outcome: str = "success", events: list[str] | None = None) -> None:
        self.outcome = outcome
        self.events = events if events is not None else []
        self.commands: list[LoginCommand] = []

    def execute(self, command: LoginCommand) -> CommittedSessionCookie:
        self.commands.append(command)
        self.events.append("login")
        if self.outcome == "invalid":
            raise InvalidCredentials()
        if self.outcome == "validation":
            raise LoginValidationError({"email": "invalid"})
        if self.outcome == "error":
            raise RuntimeError(
                "email=person@example.com password=secret hash=digest token=opaque sql=SELECT"
            )
        self.events.append("committed")
        return CommittedSessionCookie(RawSessionToken(RAW_TOKEN), EXPIRES_AT)


def _client(fake: FakeLogin, *, secure: bool = False) -> TestClient:
    api = FastAPI()
    api.add_exception_handler(
        # The application handler is intentionally installed on this isolated app
        # just as main installs it on the runtime app.
        RequestValidationError,
        registration_request_validation_handler,
    )
    login_provider = lambda: fake
    cookie_security_provider = lambda: secure
    api.include_router(build_login_router(login_provider, cookie_security_provider))
    return TestClient(api, raise_server_exceptions=False)


def test_login_success_is_empty_204_and_writes_cookie_after_commit(monkeypatch) -> None:
    events: list[str] = []
    fake = FakeLogin(events=events)

    def write_cookie(response, handoff, secure):
        events.append("writer")
        response.set_cookie(
            key="flock_session",
            value="opaque-cookie",
            secure=secure,
            httponly=True,
            samesite="lax",
            path="/",
        )

    monkeypatch.setattr(login_router_module, "write_session_cookie", write_cookie)

    with _client(fake, secure=True) as client:
        response = client.post(
            "/auth/login",
            json={"email": "person@example.com", "password": " exact password "},
        )

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers.get("set-cookie") == (
        "flock_session=opaque-cookie; HttpOnly; Path=/; SameSite=lax; Secure"
    )
    assert events == ["login", "committed", "writer"]
    assert fake.commands == [
        LoginCommand(email="person@example.com", password=" exact password ")
    ]


@pytest.mark.parametrize(
    ("payload", "expected_fields"),
    [
        ({"password": "pw"}, {"email": "invalid"}),
        ({"email": "person@example.com"}, {"password": "invalid"}),
        ({"email": 42, "password": "pw"}, {"email": "invalid"}),
        ({"email": "person@example.com", "password": False}, {"password": "invalid"}),
        (
            {"email": "person@example.com", "password": "pw", "extra": "nope"},
            {"extra": "invalid"},
        ),
        ({"email": None, "password": None}, {"email": "invalid", "password": "invalid"}),
    ],
)
def test_login_strict_object_validation_uses_route_scoped_fields(
    payload: dict, expected_fields: dict[str, str]
) -> None:
    fake = FakeLogin()
    with _client(fake) as client:
        response = client.post("/auth/login", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "fields": expected_fields}
    }
    assert fake.commands == []
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("body", ["{", "null", "[]", '"text"'])
def test_login_malformed_or_non_object_body_uses_body_field(body: str) -> None:
    fake = FakeLogin()
    with _client(fake) as client:
        response = client.post(
            "/auth/login",
            content=body,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "fields": {"body": "invalid"}}
    }
    assert fake.commands == []
    assert "set-cookie" not in response.headers


def test_login_non_json_body_uses_body_field() -> None:
    fake = FakeLogin()
    with _client(fake) as client:
        response = client.post(
            "/auth/login",
            content="plain text",
            headers={"content-type": "text/plain"},
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "fields": {"body": "invalid"}}
    }
    assert fake.commands == []
    assert "set-cookie" not in response.headers


def test_login_invalid_credentials_are_generic_without_www_authenticate_or_cookie() -> None:
    fake = FakeLogin(outcome="invalid")
    with _client(fake) as client:
        response = client.post(
            "/auth/login",
            json={"email": "person@example.com", "password": "wrong"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "invalid_credentials"}}
    assert "www-authenticate" not in response.headers
    assert "set-cookie" not in response.headers


def test_unexpected_failures_are_generic_and_redacted() -> None:
    fake = FakeLogin(outcome="error")
    with _client(fake) as client:
        response = client.post(
            "/auth/login",
            json={"email": "person@example.com", "password": "secret"},
        )

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error"}}
    assert "set-cookie" not in response.headers
    for secret in ("person@example.com", "secret", "digest", "opaque", "SELECT"):
        assert secret not in response.text


def test_failed_login_preserves_existing_client_cookie_and_never_writes() -> None:
    fake = FakeLogin(outcome="invalid")
    with _client(fake) as client:
        client.cookies.set("flock_session", "existing-cookie")
        response = client.post(
            "/auth/login",
            json={"email": "person@example.com", "password": "wrong"},
        )

        assert response.status_code == 401
        assert response.headers.get("set-cookie") is None
        assert client.cookies.get("flock_session") == "existing-cookie"


def test_login_validation_and_operational_failures_do_not_invoke_cookie_writer(monkeypatch) -> None:
    calls: list[str] = []

    def unexpected_writer(*args, **kwargs):
        calls.append("writer")
        raise AssertionError("writer must not run for a failed login")

    monkeypatch.setattr(login_router_module, "write_session_cookie", unexpected_writer)

    for outcome, payload in (
        ("invalid", {"email": "person@example.com", "password": "wrong"}),
        ("error", {"email": "person@example.com", "password": "secret"}),
    ):
        fake = FakeLogin(outcome=outcome)
        with _client(fake) as client:
            response = client.post("/auth/login", json=payload)
        assert response.status_code == (401 if outcome == "invalid" else 500)
        assert "set-cookie" not in response.headers

    assert calls == []


def test_login_request_model_exposes_exactly_email_and_password() -> None:
    from app.auth.infrastructure.login_router import LoginRequest

    assert set(LoginRequest.model_fields) == {"email", "password"}
    assert LoginRequest.model_config["extra"] == "forbid"
    assert LoginRequest.model_fields["email"].annotation is str
    assert LoginRequest.model_fields["password"].annotation is str
