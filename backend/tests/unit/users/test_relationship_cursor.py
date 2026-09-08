import base64
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.users.application.public_social_reads import (
    RelationshipCursor, RelationshipDirection, RelationshipScope, ScopedRelationshipCursor,
)
from app.users.infrastructure.relationship_cursor import decode_relationship_cursor, encode_relationship_cursor


BOUNDARY = RelationshipCursor(
    datetime(2026, 9, 7, 12, 0, 0, 123456, tzinfo=timezone.utc),
    UUID("550e8400-e29b-41d4-a716-446655440000"),
)
SCOPE = RelationshipScope(RelationshipDirection.FOLLOWERS, "alice_42")


def test_relationship_cursor_is_canonical_unpadded_and_round_trips() -> None:
    cursor = ScopedRelationshipCursor(SCOPE, BOUNDARY)
    encoded = encode_relationship_cursor(cursor)
    assert "=" not in encoded
    assert base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode() == (
        '{"v":1,"direction":"followers","username":"alice_42",'
        '"created_at":"2026-09-07T12:00:00.123456Z",'
        '"id":"550e8400-e29b-41d4-a716-446655440000"}'
    )
    assert decode_relationship_cursor(encoded) == cursor


@pytest.mark.parametrize("mutator", [
    lambda value: value + "=",
    lambda value: base64.urlsafe_b64encode(b'{"v":1}').decode().rstrip("="),
    lambda value: base64.urlsafe_b64encode(json.dumps({
        "v": 1, "username": "alice_42", "direction": "followers",
        "created_at": "2026-09-07T12:00:00.123456Z",
        "id": "550e8400-e29b-41d4-a716-446655440000",
    }, separators=(",", ":")).encode()).decode().rstrip("="),
])
def test_relationship_cursor_rejects_noncanonical_transport_or_payload(mutator) -> None:
    valid = encode_relationship_cursor(ScopedRelationshipCursor(SCOPE, BOUNDARY))
    with pytest.raises(ValueError):
        decode_relationship_cursor(mutator(valid))
