"""Canonical cursor transport contract."""

import base64
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.tweets.application.errors import InvalidFeedCursor
from app.tweets.application.ports import FeedCursor
from app.tweets.infrastructure.cursor import decode_cursor, encode_cursor

BOUNDARY = FeedCursor(
    created_at=datetime(2026, 9, 7, 12, 34, 56, 123456, tzinfo=timezone.utc),
    tweet_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
)
PAYLOAD = b'{"v":1,"created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'
VECTOR = base64.urlsafe_b64encode(PAYLOAD).decode().rstrip("=")


def _encoded(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def test_cursor_emits_exact_canonical_vector_and_round_trips() -> None:
    assert encode_cursor(BOUNDARY) == VECTOR
    assert decode_cursor(VECTOR) == BOUNDARY
    assert "=" not in VECTOR


@pytest.mark.parametrize(
    "value",
    [
        "", VECTOR + "=", "%%%", _encoded(b"\xff"), _encoded(b"null"),
        _encoded(b'{"v":1,"v":1,"created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'),
        _encoded(b'{"v":1,"created_at":"2026-09-07T12:34:56.123456Z"}'),
        _encoded(b'{"v":1,"created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000","x":1}'),
        _encoded(b'{"v":true,"created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'),
        _encoded(b'{"v":2,"created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'),
        _encoded(b'{"v":1,"created_at":"2026-09-07T12:34:56Z","id":"550e8400-e29b-41d4-a716-446655440000"}'),
        _encoded(b'{"v":1,"created_at":"2026-09-07T12:34:56.123456Z","id":"550E8400-E29B-41D4-A716-446655440000"}'),
        _encoded(json.dumps({"id": str(BOUNDARY.tweet_id), "created_at": "2026-09-07T12:34:56.123456Z", "v": 1}).encode()),
    ],
)
def test_cursor_rejects_noncanonical_transport(value: str) -> None:
    with pytest.raises(InvalidFeedCursor):
        decode_cursor(value)
