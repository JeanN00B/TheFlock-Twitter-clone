import asyncio
from collections.abc import Iterable

import pytest

from app.auth.infrastructure.origin_middleware import LoginOriginMiddleware

pytestmark = pytest.mark.unit


class Probe:
    def __init__(self, response_status: int = 204, response_body: bytes = b"", *, vary: str | None = None):
        self.response_status = response_status
        self.response_body = response_body
        self.vary = vary
        self.called = False
        self.receive_calls = 0

    async def __call__(self, scope, receive, send):
        self.called = True
        await receive()
        headers = [(b"content-type", b"application/json")]
        if self.vary is not None:
            headers.append((b"vary", self.vary.encode("ascii")))
        await send(
            {
                "type": "http.response.start",
                "status": self.response_status,
                "headers": headers,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": self.response_body,
                "more_body": False,
            }
        )


def _run_request(
    app,
    *,
    method: str = "POST",
    path: str = "/auth/login",
    headers: Iterable[tuple[bytes, bytes]] = (),
    body: bytes = b'{"email":"person@example.com","password":"pw"}',
):
    probe_receive_calls = 0
    messages = []

    async def receive():
        nonlocal probe_receive_calls
        probe_receive_calls += 1
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": list(headers),
        "server": ("testserver", 443),
        "client": ("testclient", 50000),
    }
    asyncio.run(app(scope, receive, send))

    start = next(message for message in messages if message["type"] == "http.response.start")
    body_messages = [message for message in messages if message["type"] == "http.response.body"]
    response_headers = {}
    for name, value in start["headers"]:
        response_headers.setdefault(name.decode("latin1").lower(), []).append(
            value.decode("latin1")
        )
    return start["status"], response_headers, b"".join(
        message.get("body", b"") for message in body_messages
    ), probe_receive_calls


def _middleware(probe, allowed_origins=("https://frontend.example",)):
    return LoginOriginMiddleware(probe, allowed_origins=allowed_origins)


def test_disallowed_actual_origin_is_rejected_before_body_or_downstream_work():
    probe = Probe(response_status=204, response_body=b"should not be reached")
    middleware = _middleware(probe)

    status, headers, body, receive_calls = _run_request(
        middleware,
        headers=[(b"origin", b"https://untrusted.example")],
    )

    assert status == 403
    assert body == b'{"error":{"code":"origin_not_allowed"}}'
    assert probe.called is False
    assert receive_calls == 0
    assert "access-control-allow-origin" not in headers
    assert "access-control-allow-credentials" not in headers
    assert "set-cookie" not in headers


def test_missing_origin_is_non_cors_and_dispatches_without_cors_headers():
    probe = Probe(response_status=204)

    status, headers, body, receive_calls = _run_request(_middleware(probe))

    assert status == 204
    assert body == b""
    assert probe.called is True
    assert receive_calls == 1
    assert "access-control-allow-origin" not in headers
    assert "access-control-allow-credentials" not in headers
    assert "vary" not in headers


def test_normalized_allowed_origin_is_echoed_using_the_supplied_value():
    probe = Probe(response_status=204)

    status, headers, body, receive_calls = _run_request(
        _middleware(probe),
        headers=[(b"origin", b"HTTPS://FRONTEND.EXAMPLE:443")],
    )

    assert status == 204
    assert body == b""
    assert receive_calls == 1
    assert headers["access-control-allow-origin"] == ["HTTPS://FRONTEND.EXAMPLE:443"]
    assert headers["access-control-allow-credentials"] == ["true"]


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (204, b""),
        (401, b'{"error":{"code":"invalid_credentials"}}'),
        (422, b'{"error":{"code":"validation_error","fields":{"body":"invalid"}}}'),
        (500, b'{"error":{"code":"internal_error"}}'),
    ],
)
def test_allowed_origin_headers_are_added_to_every_login_outcome(status, body):
    probe = Probe(response_status=status, response_body=body, vary="Accept-Encoding")

    response_status, headers, response_body, receive_calls = _run_request(
        _middleware(probe),
        headers=[(b"origin", b"https://frontend.example")],
        body=b"request body",
    )

    assert response_status == status
    assert response_body == body
    assert receive_calls == 1
    assert headers["access-control-allow-origin"] == ["https://frontend.example"]
    assert headers["access-control-allow-credentials"] == ["true"]
    assert set(headers["vary"][0].lower().split(", ")) == {"accept-encoding", "origin"}


def test_null_origin_is_not_allowed():
    probe = Probe()

    status, headers, body, receive_calls = _run_request(
        _middleware(probe), headers=[(b"origin", b"null")]
    )

    assert status == 403
    assert body == b'{"error":{"code":"origin_not_allowed"}}'
    assert probe.called is False
    assert receive_calls == 0
    assert "access-control-allow-origin" not in headers
    assert "set-cookie" not in headers


@pytest.mark.parametrize(
    "origin",
    [
        "https://frontend.example.attacker",
        "https://frontend.example/path",
        "https://frontend.example?next=/login",
        "https://frontend.example#fragment",
        "https://user:password@frontend.example",
        "https://frontend.example:443.attacker",
    ],
)
def test_origin_matching_is_exact_and_does_not_accept_prefix_path_query_fragment_or_credentials(
    origin,
):
    probe = Probe()

    status, headers, body, receive_calls = _run_request(
        _middleware(probe), headers=[(b"origin", origin.encode("ascii"))]
    )

    assert status == 403
    assert body == b'{"error":{"code":"origin_not_allowed"}}'
    assert probe.called is False
    assert receive_calls == 0
    assert "access-control-allow-origin" not in headers
    assert "access-control-allow-credentials" not in headers


def test_non_login_paths_are_not_origin_protected():
    probe = Probe(response_status=200, response_body=b"health")

    status, headers, body, receive_calls = _run_request(
        _middleware(probe),
        path="/health",
        headers=[(b"origin", b"https://untrusted.example")],
    )

    assert status == 200
    assert body == b"health"
    assert probe.called is True
    assert receive_calls == 1
    assert "access-control-allow-origin" not in headers


def test_valid_json_post_preflight_returns_cors_grant_without_dispatch_or_cookie():
    probe = Probe(response_status=500, response_body=b"should not be reached")

    status, headers, body, receive_calls = _run_request(
        _middleware(probe),
        method="OPTIONS",
        headers=[
            (b"origin", b"https://frontend.example"),
            (b"access-control-request-method", b"POST"),
            (b"access-control-request-headers", b"content-type"),
        ],
    )

    assert status == 204
    assert body == b""
    assert probe.called is False
    assert receive_calls == 0
    assert headers["access-control-allow-origin"] == ["https://frontend.example"]
    assert headers["access-control-allow-credentials"] == ["true"]
    assert headers["access-control-allow-methods"] == ["POST"]
    assert headers["access-control-allow-headers"] == ["content-type"]
    assert headers["vary"] == ["Origin"]
    assert "set-cookie" not in headers


@pytest.mark.parametrize(
    "headers",
    [
        [(b"origin", b"https://frontend.example")],
        [
            (b"origin", b"https://frontend.example"),
            (b"access-control-request-method", b"GET"),
            (b"access-control-request-headers", b"content-type"),
        ],
        [
            (b"origin", b"https://frontend.example"),
            (b"access-control-request-method", b"POST"),
            (b"access-control-request-headers", b"x-not-json"),
        ],
        [
            (b"origin", b"https://frontend.example"),
            (b"access-control-request-method", b"POST"),
            (b"access-control-request-headers", b"content-type,"),
        ],
        [
            (b"origin", b"https://frontend.example"),
            (b"access-control-request-method", b"POST"),
            (b"access-control-request-headers", b"content-type"),
            (b"cookie", b"flock_session=existing"),
        ],
    ],
)
def test_malformed_json_post_preflight_is_denied_without_cors_grant(headers):
    probe = Probe()

    status, response_headers, body, receive_calls = _run_request(
        _middleware(probe), method="OPTIONS", headers=headers
    )

    assert status == 403
    assert body == b'{"error":{"code":"origin_not_allowed"}}'
    assert probe.called is False
    assert receive_calls == 0
    assert "access-control-allow-origin" not in response_headers
    assert "access-control-allow-credentials" not in response_headers
    assert "set-cookie" not in response_headers


def test_disallowed_actual_request_cannot_receive_downstream_cookie_or_cors_grant():
    probe = Probe(response_status=204)

    status, headers, body, receive_calls = _run_request(
        _middleware(probe),
        headers=[
            (b"origin", b"https://untrusted.example"),
            (b"cookie", b"flock_session=existing"),
        ],
    )

    assert status == 403
    assert body == b'{"error":{"code":"origin_not_allowed"}}'
    assert receive_calls == 0
    assert "set-cookie" not in headers
    assert "access-control-allow-origin" not in headers
    assert "access-control-allow-credentials" not in headers
