from base64 import urlsafe_b64encode
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.application.login import RawSessionToken
from app.auth.application.session_access import Unauthenticated
from app.auth.infrastructure.session_router import build_session_router
from app.main import unauthenticated_exception_handler
from app.users.domain.user import PublicUser


pytestmark = pytest.mark.unit


PUBLIC_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
RAW_BYTES = b"r" * 32
RAW_TOKEN = RawSessionToken(RAW_BYTES)
COOKIE = urlsafe_b64encode(RAW_BYTES).rstrip(b"=").decode("ascii")
NOW = datetime(2026, 9, 6, 13, 10, 26, tzinfo=timezone.utc)
USER = PublicUser(
    id=PUBLIC_ID,
    email="person@example.com",
    username="person_1",
    display_name="Person Example",
    created_at=NOW,
    updated_at=NOW,
)


class RecordingSessionAccess:
    def __init__(
        self,
        user: PublicUser | None = USER,
        resolve_error: Exception | None = None,
        revoke_error: Exception | None = None,
    ) -> None:
        self.user = user
        self.resolve_error = resolve_error
        self.revoke_error = revoke_error
        self.resolved: list[RawSessionToken] = []
        self.revoked: list[RawSessionToken] = []

    def resolve(self, token: RawSessionToken) -> PublicUser:
        self.resolved.append(token)
        if self.resolve_error is not None:
            raise self.resolve_error
        assert self.user is not None
        return self.user

    def revoke(self, token: RawSessionToken) -> None:
        self.revoked.append(token)
        if self.revoke_error is not None:
            raise self.revoke_error


def _client(fake: RecordingSessionAccess, *, secure: bool = False) -> TestClient:
    api = FastAPI()
    api.add_exception_handler(Unauthenticated, unauthenticated_exception_handler)
    api.include_router(build_session_router(lambda: fake, lambda: secure))
    return TestClient(api, raise_server_exceptions=False)


def test_me_maps_the_credential_free_public_user_and_utc_timestamps() -> None:
    fake = RecordingSessionAccess()

    with _client(fake) as client:
        response = client.get("/auth/me", cookies={"flock_session": COOKIE})

    assert response.status_code == 200
    assert response.json() == {
        "id": str(PUBLIC_ID),
        "email": "person@example.com",
        "username": "person_1",
        "display_name": "Person Example",
        "created_at": "2026-09-06T13:10:26Z",
        "updated_at": "2026-09-06T13:10:26Z",
    }
    assert [token.as_bytes() for token in fake.resolved] == [RAW_BYTES]
    assert fake.revoked == []


@pytest.mark.parametrize(
    "cookie",
    [None, "not-a-session", COOKIE + "="],
    ids=["missing", "malformed", "padded"],
)
def test_me_missing_or_malformed_cookie_is_generic_unauthenticated(
    cookie: str | None,
) -> None:
    fake = RecordingSessionAccess()
    request_cookies = {} if cookie is None else {"flock_session": cookie}

    with _client(fake) as client:
        response = client.get("/auth/me", cookies=request_cookies)

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthenticated"}}
    assert fake.resolved == []
    assert "flock_session" not in response.headers


def test_me_unusable_session_is_generic_unauthenticated() -> None:
    fake = RecordingSessionAccess(resolve_error=Unauthenticated())

    with _client(fake) as client:
        response = client.get("/auth/me", cookies={"flock_session": COOKIE})

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthenticated"}}
    assert [token.as_bytes() for token in fake.resolved] == [RAW_BYTES]


@pytest.mark.parametrize(
    "cookie",
    [None, "not-a-session", COOKIE + "="],
    ids=["missing", "malformed", "padded"],
)
def test_logout_is_idempotent_for_missing_or_malformed_cookie_and_clears_cookie(
    cookie: str | None,
) -> None:
    fake = RecordingSessionAccess()
    request_cookies = {} if cookie is None else {"flock_session": cookie}

    with _client(fake) as client:
        response = client.post("/auth/logout", cookies=request_cookies)

    assert response.status_code == 204
    assert response.content == b""
    assert fake.revoked == []
    assert response.headers["set-cookie"].startswith('flock_session="";')
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert "Path=/" in response.headers["set-cookie"]
    assert "Domain=" not in response.headers["set-cookie"]


def test_logout_revokes_valid_cookie_and_clears_cookie() -> None:
    fake = RecordingSessionAccess()

    with _client(fake, secure=True) as client:
        response = client.post("/auth/logout", cookies={"flock_session": COOKIE})

    assert response.status_code == 204
    assert response.content == b""
    assert [token.as_bytes() for token in fake.revoked] == [RAW_BYTES]
    assert "Secure" in response.headers["set-cookie"]


def test_logout_operational_failure_is_generic_and_still_clears_cookie() -> None:
    fake = RecordingSessionAccess(
        revoke_error=RuntimeError(
            "token=opaque-token user=person@example.com sql=SELECT secret"
        )
    )

    with _client(fake) as client:
        response = client.post("/auth/logout", cookies={"flock_session": COOKIE})

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error"}}
    assert response.headers["set-cookie"].startswith('flock_session="";')
    for secret in ("opaque-token", "person@example.com", "SELECT", "secret"):
        assert secret not in response.text
