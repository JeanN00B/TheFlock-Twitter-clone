"""Narrow pre-dispatch Origin enforcement for the login endpoint."""

from collections.abc import Iterable
import re
from typing import Any

from app.core.settings import normalize_origin


_LOGIN_PATH = "/auth/login"
_ORIGIN_HEADER = b"origin"
_CREDENTIALS_HEADER = b"access-control-allow-credentials"
_ALLOW_ORIGIN_HEADER = b"access-control-allow-origin"
_VARY_HEADER = b"vary"
_HEADER_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_DENIAL_BODY = b'{"error":{"code":"origin_not_allowed"}}'


class LoginOriginMiddleware:
    """Enforce exact configured origins before the login app can read a body."""

    def __init__(self, app: Any, allowed_origins: Iterable[str] = (), *, settings: Any = None):
        if settings is not None:
            allowed_origins = settings.allowed_origins
        elif hasattr(allowed_origins, "allowed_origins"):
            allowed_origins = allowed_origins.allowed_origins
        if isinstance(allowed_origins, str):
            raise TypeError("allowed_origins must be an iterable of origins")
        self.app = app
        self.allowed_origins = frozenset(normalize_origin(origin) for origin in allowed_origins)

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope.get("type") != "http" or scope.get("path") != _LOGIN_PATH:
            await self.app(scope, receive, send)
            return

        origin_values = _header_values(scope, _ORIGIN_HEADER)
        if not origin_values:
            await self.app(scope, receive, send)
            return
        if len(origin_values) != 1:
            await _send_denial(send)
            return

        origin = origin_values[0]
        normalized_origin = _normalized_request_origin(origin)
        if normalized_origin not in self.allowed_origins:
            await _send_denial(send)
            return

        if scope.get("method") == "OPTIONS":
            if not _valid_json_post_preflight(scope):
                await _send_denial(send)
                return
            await _send_preflight(send, origin)
            return

        async def send_with_cors(message: dict[str, Any]) -> None:
            if message.get("type") != "http.response.start":
                await send(message)
                return
            await send(_with_cors_headers(message, origin))

        await self.app(scope, receive, send_with_cors)


def _header_values(scope: dict[str, Any], name: bytes) -> list[str]:
    return [value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == name]


def _normalized_request_origin(origin: str) -> str | None:
    try:
        return normalize_origin(origin)
    except (TypeError, ValueError):
        return None


def _valid_json_post_preflight(scope: dict[str, Any]) -> bool:
    method_values = _header_values(scope, b"access-control-request-method")
    requested_headers_values = _header_values(scope, b"access-control-request-headers")
    if len(method_values) != 1 or method_values[0] != "POST":
        return False
    if len(requested_headers_values) != 1:
        return False
    if _header_values(scope, b"cookie"):
        return False

    requested_headers = [part.strip().lower() for part in requested_headers_values[0].split(",")]
    return (
        bool(requested_headers)
        and all(_HEADER_TOKEN.fullmatch(header) for header in requested_headers)
        and requested_headers == ["content-type"]
    )


def _with_cors_headers(message: dict[str, Any], origin: str) -> dict[str, Any]:
    headers = []
    vary_values = []
    for name, value in message.get("headers", []):
        lowered_name = name.lower()
        if lowered_name in {_ALLOW_ORIGIN_HEADER, _CREDENTIALS_HEADER}:
            continue
        if lowered_name == _VARY_HEADER:
            vary_values.extend(
                part.strip() for part in value.decode("latin-1").split(",") if part.strip()
            )
        else:
            headers.append((name, value))

    if not any(value.lower() == "origin" for value in vary_values):
        vary_values.append("Origin")
    headers.extend(
        [
            (_ALLOW_ORIGIN_HEADER, origin.encode("latin-1")),
            (_CREDENTIALS_HEADER, b"true"),
            (_VARY_HEADER, ", ".join(vary_values).encode("latin-1")),
        ]
    )
    return {**message, "headers": headers}


async def _send_denial(send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_DENIAL_BODY)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _DENIAL_BODY, "more_body": False})


async def _send_preflight(send, origin: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 204,
            "headers": [
                (b"content-length", b"0"),
                (_ALLOW_ORIGIN_HEADER, origin.encode("latin-1")),
                (_CREDENTIALS_HEADER, b"true"),
                (b"access-control-allow-methods", b"POST"),
                (b"access-control-allow-headers", b"content-type"),
                (_VARY_HEADER, b"Origin"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": b"", "more_body": False})
