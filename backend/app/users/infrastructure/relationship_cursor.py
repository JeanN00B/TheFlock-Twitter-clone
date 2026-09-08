"""Canonical transport for relationship-list boundaries."""

import base64
import json
from datetime import datetime, timezone
from uuid import UUID

from app.users.application.public_social_reads import (
    RelationshipCursor, RelationshipDirection, RelationshipScope, ScopedRelationshipCursor,
)
from app.users.domain.user import canonicalize_username

_KEYS = ["v", "direction", "username", "created_at", "id"]


def encode_relationship_cursor(cursor: ScopedRelationshipCursor) -> str:
    timestamp = cursor.boundary.created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    payload = {"v": 1, "direction": cursor.scope.direction.value,
               "username": cursor.scope.username, "created_at": timestamp,
               "id": str(cursor.boundary.id)}
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")


def decode_relationship_cursor(value: str) -> ScopedRelationshipCursor:
    try:
        if not isinstance(value, str) or not value or "=" in value:
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        pairs = json.loads(raw, object_pairs_hook=list)
        if [key for key, _ in pairs] != _KEYS:
            raise ValueError
        payload = dict(pairs)
        if payload["v"] != 1:
            raise ValueError
        direction = RelationshipDirection(payload["direction"])
        username = payload["username"]
        timestamp = datetime.strptime(payload["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        public_id = UUID(payload["id"])
        if public_id.version != 4 or canonicalize_username(username) != username:
            raise ValueError
        cursor = ScopedRelationshipCursor(
            RelationshipScope(direction, username), RelationshipCursor(timestamp, public_id)
        )
        if encode_relationship_cursor(cursor) != value:
            raise ValueError
        return cursor
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid relationship cursor") from error
