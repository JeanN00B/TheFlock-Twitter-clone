"""Focused HTTP contract tests for authenticated tweet creation."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.auth.application.session_access import Unauthenticated
from app.tweets.application.create_tweet import CreateTweetCommand
from app.tweets.application.delete_tweet import DeleteTweetCommand
from app.tweets.application.errors import TweetForbidden, TweetNotFound, TweetValidationError
from app.tweets.application.set_like_state import SetLikeStateCommand
from app.tweets.application.list_tweet_feed import ListTweetFeedQuery, TweetPage
from app.tweets.application.ports import FeedCursor
from app.tweets.domain.tweet import LikeState, PublicAuthorSummary, PublicTweet
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


class RecordingListTweetFeed:
    def __init__(self) -> None:
        self.queries: list[ListTweetFeedQuery] = []

    def execute(self, query: ListTweetFeedQuery) -> TweetPage:
        self.queries.append(query)
        item = PublicTweet(TWEET_ID, "hello", NOW, PublicAuthorSummary(ACTOR_ID, "alice", "Alice Example"))
        return TweetPage((item,), FeedCursor(NOW, TWEET_ID))


@pytest.fixture()
def feed_client():
    from app.composition import current_user_dependency, get_list_tweet_feed
    from app.main import app

    use_case = RecordingListTweetFeed()
    actor = PublicUser(ACTOR_ID, "private@example.com", "alice", "Alice Example", NOW, NOW)
    app.dependency_overrides[get_list_tweet_feed] = lambda: use_case
    app.dependency_overrides[current_user_dependency] = lambda: actor
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, use_case
    finally:
        app.dependency_overrides.clear()


def test_profile_feed_canonicalizes_username_before_query(feed_client):
    from app.tweets.application.ports import FeedKind, FeedScope

    client, use_case = feed_client
    response = client.get("/tweets?feed=profile&username=%20CASE_CHECK%20")

    assert response.status_code == 200
    assert use_case.queries == [ListTweetFeedQuery(scope=FeedScope(FeedKind.PROFILE, "case_check"), actor_id=ACTOR_ID)]


def test_feed_defaults_page_size_and_returns_exact_envelope(feed_client):
    client, use_case = feed_client
    response = client.get("/tweets")
    assert response.status_code == 200
    assert set(response.json()) == {"items", "next_cursor"}
    assert response.json()["items"] == [{
        "id": str(TWEET_ID), "text": "hello", "created_at": "2026-09-07T12:34:56.123456Z",
        "author": {"id": str(ACTOR_ID), "username": "alice", "display_name": "Alice Example"},
    }]
    assert response.json()["next_cursor"]
    assert use_case.queries == [ListTweetFeedQuery(page_size=20, actor_id=ACTOR_ID)]


@pytest.mark.parametrize("query", ["page_size=0", "page_size=51", "page_size=", "page_size=1.0", "page_size=true", "page_size=01", "page_size=2&page_size=3"])
def test_feed_rejects_noncanonical_page_size_without_query(feed_client, query):
    client, use_case = feed_client
    response = client.get(f"/tweets?{query}")
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "validation_error", "fields": {"page_size": "invalid"}}}
    assert use_case.queries == []


def test_feed_decodes_cursor_and_allows_new_page_size(feed_client):
    from app.tweets.infrastructure.cursor import encode_cursor
    client, use_case = feed_client
    cursor = encode_cursor(FeedCursor(NOW, TWEET_ID))
    response = client.get(f"/tweets?page_size=50&cursor={cursor}")
    assert response.status_code == 200
    assert use_case.queries == [ListTweetFeedQuery(page_size=50, before=FeedCursor(NOW, TWEET_ID), actor_id=ACTOR_ID)]


@pytest.mark.parametrize("query", ["cursor=", "cursor=bad%", "cursor=a&cursor=b"])
def test_feed_rejects_invalid_cursor_without_query(feed_client, query):
    client, use_case = feed_client
    response = client.get(f"/tweets?{query}")
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "validation_error", "fields": {"cursor": "invalid"}}}
    assert use_case.queries == []


class RecordingDeleteTweet:
    def __init__(self) -> None:
        self.commands: list[DeleteTweetCommand] = []
        self.error: Exception | None = None

    def execute(self, command: DeleteTweetCommand) -> None:
        self.commands.append(command)
        if self.error is not None:
            raise self.error


@pytest.fixture()
def delete_client():
    from app.composition import current_user_dependency, get_delete_tweet
    from app.main import app

    use_case = RecordingDeleteTweet()
    actor = PublicUser(ACTOR_ID, "private@example.com", "alice", "Alice Example", NOW, NOW)
    app.dependency_overrides[get_delete_tweet] = lambda: use_case
    app.dependency_overrides[current_user_dependency] = lambda: actor
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, use_case
    finally:
        app.dependency_overrides.clear()


def test_delete_owner_returns_exact_empty_204(delete_client):
    client, use_case = delete_client

    response = client.delete(f"/tweets/{TWEET_ID}")

    assert response.status_code == 204
    assert response.content == b""
    assert use_case.commands == [DeleteTweetCommand(tweet_id=TWEET_ID, requester_id=ACTOR_ID)]


@pytest.mark.parametrize("tweet_id", ["not-a-uuid", "22222222222242228222222222222222", "22222222-2222-1222-8222-222222222222", "abcdefab-cdef-4abc-8def-abcdefabcdef".upper()])
def test_delete_rejects_noncanonical_uuid_v4_without_calling_use_case(delete_client, tweet_id):
    client, use_case = delete_client

    response = client.delete(f"/tweets/{tweet_id}")

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "validation_error", "fields": {"tweet_id": "invalid"}}}
    assert use_case.commands == []


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [(TweetForbidden(), 403, "forbidden"), (TweetNotFound(), 404, "not_found")],
)
def test_delete_maps_public_outcomes(delete_client, error, status_code, code):
    client, use_case = delete_client
    use_case.error = error

    response = client.delete(f"/tweets/{TWEET_ID}")

    assert response.status_code == status_code
    assert response.json() == {"error": {"code": code}}


class RecordingLikeState:
    def __init__(self) -> None:
        self.commands: list[SetLikeStateCommand] = []
        self.error: Exception | None = None

    def execute(self, command: SetLikeStateCommand) -> LikeState:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return LikeState(command.tweet_id, 1 if command.liked else 0, command.liked)


@pytest.fixture()
def like_client():
    from app.composition import current_user_dependency, get_set_like_state
    from app.main import app

    use_case = RecordingLikeState()
    actor = PublicUser(ACTOR_ID, "private@example.com", "alice", "Alice Example", NOW, NOW)
    app.dependency_overrides[get_set_like_state] = lambda: use_case
    app.dependency_overrides[current_user_dependency] = lambda: actor
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, use_case
    finally:
        app.dependency_overrides.clear()


def test_like_route_returns_exact_state_for_authenticated_actor(like_client):
    client, use_case = like_client

    response = client.post(f"/tweets/{TWEET_ID}/like")

    assert response.status_code == 200
    assert response.json() == {
        "tweet_id": str(TWEET_ID),
        "like_count": 1,
        "liked_by_actor": True,
    }
    assert use_case.commands == [SetLikeStateCommand(TWEET_ID, ACTOR_ID, True)]


def test_like_routes_set_state_and_ignore_request_bodies(like_client):
    client, use_case = like_client

    posted = client.post(f"/tweets/{TWEET_ID}/like", json={"actor_id": "other", "like_count": 99})
    deleted = client.request("DELETE", f"/tweets/{TWEET_ID}/like", content=b'{"ignored":', headers={"content-type": "application/json"})

    assert posted.status_code == deleted.status_code == 200
    assert posted.json() == {"tweet_id": str(TWEET_ID), "like_count": 1, "liked_by_actor": True}
    assert deleted.json() == {"tweet_id": str(TWEET_ID), "like_count": 0, "liked_by_actor": False}
    assert use_case.commands == [
        SetLikeStateCommand(TWEET_ID, ACTOR_ID, True),
        SetLikeStateCommand(TWEET_ID, ACTOR_ID, False),
    ]


@pytest.mark.parametrize(
    "tweet_id",
    ["not-a-uuid", "22222222222242228222222222222222", "22222222-2222-1222-8222-222222222222", "ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF"],
)
@pytest.mark.parametrize("method", ["post", "delete"])
def test_like_routes_reject_noncanonical_ids_without_use_case(like_client, tweet_id, method):
    client, use_case = like_client

    response = getattr(client, method)(f"/tweets/{tweet_id}/like")

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "validation_error", "fields": {"tweet_id": "invalid"}}}
    assert use_case.commands == []


def test_like_authentication_precedes_malformed_id():
    from app.composition import current_user_dependency, get_set_like_state
    from app.main import app

    use_case = RecordingLikeState()
    def reject_session():
        raise Unauthenticated

    app.dependency_overrides[current_user_dependency] = reject_session
    app.dependency_overrides[get_set_like_state] = lambda: use_case
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            responses = [
                client.post("/tweets/not-a-uuid/like"),
                client.delete("/tweets/not-a-uuid/like"),
            ]
    finally:
        app.dependency_overrides.clear()

    assert [response.status_code for response in responses] == [401, 401]
    assert all(response.json() == {"error": {"code": "unauthenticated"}} for response in responses)
    assert use_case.commands == []


@pytest.mark.parametrize("method", ["post", "delete"])
def test_like_maps_not_found_without_forbidden_or_conflict(like_client, method):
    client, use_case = like_client
    use_case.error = TweetNotFound()

    response = getattr(client, method)(f"/tweets/{TWEET_ID}/like")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found"}}
    assert response.status_code not in {403, 409}
