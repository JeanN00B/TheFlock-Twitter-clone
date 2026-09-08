"""Canonical scope-bound tweet cursor transport contract."""

import base64
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.tweets.application.errors import InvalidFeedCursor
from app.tweets.application.ports import FeedCursor, FeedKind, FeedScope
from app.tweets.infrastructure.cursor import decode_cursor, encode_cursor

ALL = FeedScope(FeedKind.ALL)
FOLLOWING = FeedScope(FeedKind.FOLLOWING)
PROFILE = FeedScope(FeedKind.PROFILE, "alice_42")
BOUNDARY = FeedCursor(
    created_at=datetime(2026, 9, 7, 12, 34, 56, 123456, tzinfo=timezone.utc),
    tweet_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
    scope=ALL,
)
V2_PAYLOAD = b'{"v":2,"feed":"all","created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'
V2_VECTOR = base64.urlsafe_b64encode(V2_PAYLOAD).decode().rstrip("=")
V1_PAYLOAD = b'{"v":1,"created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'
V1_VECTOR = base64.urlsafe_b64encode(V1_PAYLOAD).decode().rstrip("=")


def _encoded(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def test_cursor_emits_exact_v2_vector_and_round_trips() -> None:
    assert encode_cursor(BOUNDARY) == V2_VECTOR
    assert decode_cursor(V2_VECTOR, ALL) == BOUNDARY
    assert "=" not in V2_VECTOR


def test_archived_v1_is_accepted_only_for_effective_all() -> None:
    assert decode_cursor(V1_VECTOR, ALL) == BOUNDARY
    for scope in (FOLLOWING, PROFILE):
        with pytest.raises(InvalidFeedCursor):
            decode_cursor(V1_VECTOR, scope)


def test_v2_cursor_is_bound_to_exact_effective_scope() -> None:
    for scope in (FOLLOWING, PROFILE):
        with pytest.raises(InvalidFeedCursor):
            decode_cursor(V2_VECTOR, scope)


@pytest.mark.parametrize(
    "value",
    [
        "", V2_VECTOR + "=", "%%%", _encoded(b"\xff"), _encoded(b"null"),
        _encoded(b'{"v":2,"v":2,"feed":"all","created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'),
        _encoded(b'{"v":2,"feed":"all","created_at":"2026-09-07T12:34:56.123456Z"}'),
        _encoded(b'{"v":2,"feed":"all","created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000","x":1}'),
        _encoded(b'{"feed":"all","v":2,"created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'),
        _encoded(b'{"v":true,"feed":"all","created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'),
        _encoded(b'{"v":3,"feed":"all","created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'),
        _encoded(b'{"v":2,"feed":"ALL","created_at":"2026-09-07T12:34:56.123456Z","id":"550e8400-e29b-41d4-a716-446655440000"}'),
        _encoded(b'{"v":2,"feed":"all","created_at":"2026-09-07T12:34:56Z","id":"550e8400-e29b-41d4-a716-446655440000"}'),
        _encoded(b'{"v":2,"feed":"all","created_at":"2026-09-07T12:34:56.123456Z","id":"550E8400-E29B-41D4-A716-446655440000"}'),
    ],
)
def test_cursor_rejects_noncanonical_transport(value: str) -> None:
    with pytest.raises(InvalidFeedCursor):
        decode_cursor(value, ALL)
