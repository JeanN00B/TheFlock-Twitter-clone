"""Focused HTTP contract tests for authenticated tweet creation."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.tweets.application.create_tweet import CreateTweetCommand
from app.tweets.application.errors import TweetValidationError
from app.tweets.domain.tweet import PublicAuthorSummary, PublicTweet
from app.users.domain.user import PublicUser

ACTOR_ID = UUID("11111111-1111-4111-8111-111111111111")
TWEET_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 9, 7, 12, 34, 56, 123456, tzinfo=timezone.utc)


class RecordingCreateTweet:
    def __init__(self) -> None:
        self.commands: list[CreateTweetCommand] = []
        self.error: Exception | None = None

    def execute(self, command: CreateTweetCommand) -> PublicTweet:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return PublicTweet(
            id=TWEET_ID,
            text=command.text.strip(),
            created_at=NOW,
            author=PublicAuthorSummary(
                id=command.author_id,
                username=command.author_username,
                display_name=command.author_display_name,
            ),
        )


@pytest.fixture()
def create_client():
    from app.composition import current_user_dependency, get_create_tweet
    from app.main import app

    use_case = RecordingCreateTweet()
    actor = PublicUser(
        id=ACTOR_ID,
        email="private@example.com",
        username="alice",
        display_name="Alice Example",
        created_at=NOW,
        updated_at=NOW,
    )
    app.dependency_overrides[get_create_tweet] = lambda: use_case
    app.dependency_overrides[current_user_dependency] = lambda: actor
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, use_case
    finally:
        app.dependency_overrides.clear()


def test_create_uses_authenticated_actor_and_returns_exact_public_projection(create_client):
    client, use_case = create_client

    response = client.post("/tweets", json={"text": "  hello  "})

    assert response.status_code == 201
    assert response.json() == {
        "id": str(TWEET_ID),
        "text": "hello",
        "created_at": "2026-09-07T12:34:56.123456Z",
        "author": {
            "id": str(ACTOR_ID),
            "username": "alice",
            "display_name": "Alice Example",
        },
    }
    assert use_case.commands == [
        CreateTweetCommand(
            text="  hello  ",
            author_id=ACTOR_ID,
            author_username="alice",
            author_display_name="Alice Example",
        )
    ]
    assert not ({"email", "updated_at", "deleted_at", "public_id", "author_id"} & response.json().keys())


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "text"),
        ({"text": None}, "text"),
        ({"text": 7}, "text"),
        ({"text": ["hello"]}, "text"),
        ({"text": "hello", "author": "other"}, "author"),
    ],
)
def test_create_rejects_non_exact_body_without_calling_use_case(create_client, payload, field):
    client, use_case = create_client

    response = client.post("/tweets", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "fields": {field: "invalid"}}
    }
    assert use_case.commands == []


def test_create_rejects_malformed_and_non_object_json(create_client):
    client, use_case = create_client

    malformed = client.post("/tweets", content=b'{"text":', headers={"content-type": "application/json"})
    array = client.post("/tweets", json=["hello"])

    assert malformed.status_code == 422
    assert malformed.json() == {"error": {"code": "validation_error", "fields": {"body": "invalid"}}}
    assert array.status_code == 422
    assert array.json() == {"error": {"code": "validation_error", "fields": {"body": "invalid"}}}
    assert use_case.commands == []


@pytest.mark.parametrize("text", ["   ", "x" * 281])
def test_create_maps_domain_text_validation_without_success(create_client, text):
    client, use_case = create_client
    use_case.error = TweetValidationError({"text"})

    response = client.post("/tweets", json={"text": text})

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "validation_error", "fields": {"text": "invalid"}}}
