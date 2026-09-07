"""Strict canonical v1 feed cursor transport."""

import base64
import binascii
import json
import re
from datetime import datetime, timezone
from uuid import UUID

from app.tweets.application.errors import InvalidFeedCursor
from app.tweets.application.ports import FeedCursor

_ALPHABET = re.compile(r"^[A-Za-z0-9_-]+$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def encode_cursor(cursor: FeedCursor) -> str:
    timestamp = cursor.created_at.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    payload = json.dumps(
        {"v": 1, "created_at": timestamp, "id": str(cursor.tweet_id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> FeedCursor:
    try:
        if type(value) is not str or not _ALPHABET.fullmatch(value) or len(value) % 4 == 1:
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        text = raw.decode("utf-8")

        def pairs_hook(pairs):
            if len({key for key, _ in pairs}) != len(pairs):
                raise ValueError
            return dict(pairs)

        payload = json.loads(text, object_pairs_hook=pairs_hook)
        if type(payload) is not dict or list(payload) != ["v", "created_at", "id"]:
            raise ValueError
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError
        timestamp_text, id_text = payload["created_at"], payload["id"]
        if type(timestamp_text) is not str or not _TIMESTAMP.fullmatch(timestamp_text):
            raise ValueError
        if type(id_text) is not str:
            raise ValueError
        created_at = datetime.strptime(timestamp_text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        tweet_id = UUID(id_text)
        if tweet_id.version != 4 or str(tweet_id) != id_text:
            raise ValueError
        cursor = FeedCursor(created_at, tweet_id)
        if encode_cursor(cursor) != value:
            raise ValueError
        return cursor
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as error:
        raise InvalidFeedCursor from error
