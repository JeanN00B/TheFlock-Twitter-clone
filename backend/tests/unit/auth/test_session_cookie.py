from base64 import urlsafe_b64decode
from datetime import datetime, timezone
from email.utils import format_datetime

import pytest
from starlette.responses import Response

from app.auth.application.login import CommittedSessionCookie, RawSessionToken
from app.auth.infrastructure.session_cookie import (
    clear_session_cookie,
    read_session_cookie,
    write_session_cookie,
)


RAW_TOKEN = bytes(range(32))
EXPIRY = datetime(2026, 9, 13, 13, 10, 26, tzinfo=timezone.utc)


def test_cookie_writer_serializes_one_unpadded_lossless_cookie_on_empty_204() -> None:
    response = Response(status_code=204)
    handoff = CommittedSessionCookie(RawSessionToken(RAW_TOKEN), EXPIRY)

    result = write_session_cookie(response, handoff, secure=False)

    assert result is None
    assert response.status_code == 204
    assert response.body == b""
    header = response.headers["set-cookie"]
    assert header.count("flock_session=") == 1
    value = header.split("flock_session=", 1)[1].split(";", 1)[0]
    assert len(value) == 43
    assert "=" not in value
    assert urlsafe_b64decode(value + "=") == RAW_TOKEN
    assert "Domain=" not in header
    assert "Path=/" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Max-Age=604800" in header
    assert f"expires={format_datetime(EXPIRY, usegmt=True)}" in header
    assert RAW_TOKEN.hex() not in header
    assert "Secure" not in header


class RecordingResponse(Response):
    def __init__(self) -> None:
        self.set_cookie_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        super().__init__(status_code=204)

    def set_cookie(self, *args: object, **kwargs: object) -> None:
        self.set_cookie_calls.append((args, kwargs))
        super().set_cookie(*args, **kwargs)


@pytest.mark.parametrize("secure", [False, True])
def test_cookie_writer_passes_exact_attributes_for_local_and_production(
    secure: bool,
) -> None:
    response = RecordingResponse()
    handoff = CommittedSessionCookie(RawSessionToken(RAW_TOKEN), EXPIRY)

    result = write_session_cookie(response, handoff, secure)

    assert result is None
    assert len(response.set_cookie_calls) == 1
    assert response.set_cookie_calls[0] == (
        (),
        {
            "key": "flock_session",
            "value": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
            "max_age": 604800,
            "expires": EXPIRY,
            "path": "/",
            "domain": None,
            "secure": secure,
            "httponly": True,
            "samesite": "lax",
        },
    )
    expected = (
        "flock_session=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8; "
        f"expires={format_datetime(EXPIRY, usegmt=True)}; HttpOnly; Max-Age=604800; "
        "Path=/; SameSite=lax"
    )
    if secure:
        expected += "; Secure"
    assert response.headers["set-cookie"] == expected
    assert "Domain=" not in response.headers["set-cookie"]


def test_cookie_writer_consumes_handoff_once_and_returns_no_raw_token() -> None:
    response = Response(status_code=204)
    handoff = CommittedSessionCookie(RawSessionToken(RAW_TOKEN), EXPIRY)

    result = write_session_cookie(response, handoff, secure=True)

    header = response.headers["set-cookie"]
    assert result is None
    assert "Secure" in header
    assert RAW_TOKEN.hex() not in repr(handoff)
    with pytest.raises(RuntimeError) as raised:
        write_session_cookie(response, handoff, secure=True)
    assert RAW_TOKEN.hex() not in str(raised.value)
    assert header == response.headers["set-cookie"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "A" * 42,
        "A" * 44,
        "A" * 42 + "=",
        "A" * 42 + "!",
        "A" * 42 + "+",
        "A" * 42 + "/",
        "é" * 43,
        "A" * 42 + "\n",
        "A" * 42 + "B",
    ],
    ids=[
        "missing",
        "empty",
        "short",
        "long",
        "padded",
        "bang",
        "plus",
        "slash",
        "non-ascii",
        "newline",
        "non-canonical-trailing-bits",
    ],
)
def test_cookie_reader_rejects_missing_malformed_and_noncanonical_values(
    value: str | None,
) -> None:
    assert read_session_cookie(value) is None


def test_cookie_reader_returns_redacted_fixed_length_token_for_valid_round_trip() -> None:
    response = Response(status_code=204)
    handoff = CommittedSessionCookie(RawSessionToken(RAW_TOKEN), EXPIRY)
    write_session_cookie(response, handoff, secure=False)
    encoded = response.headers["set-cookie"].split("flock_session=", 1)[1].split(
        ";", 1
    )[0]

    token = read_session_cookie(encoded)

    assert token is not None
    assert token.as_bytes() == RAW_TOKEN
    assert RAW_TOKEN.hex() not in repr(token)


def test_cookie_reader_rejects_non_string_values() -> None:
    assert read_session_cookie(42) is None  # type: ignore[arg-type]


@pytest.mark.parametrize("secure", [False, True])
def test_clear_cookie_expires_host_only_path_cookie(secure: bool) -> None:
    response = RecordingResponse()

    result = clear_session_cookie(response, secure=secure)

    assert result is None
    assert response.set_cookie_calls == [
        (
            ("flock_session",),
            {
                "max_age": 0,
                "expires": 0,
                "path": "/",
                "domain": None,
                "secure": secure,
                "httponly": True,
                "samesite": "lax",
            },
        )
    ]
    header = response.headers["set-cookie"]
    assert header.startswith('flock_session="";')
    assert "expires=" in header
    assert "Max-Age=0" in header
    assert "Path=/" in header
    assert "Domain=" not in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert ("; Secure" in header) is secure
