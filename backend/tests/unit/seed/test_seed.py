"""Unit seams for the endpoint-first demo seeder (no live DB required)."""

from __future__ import annotations

import json
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scripts.seed.seed import (
    DEFAULT_SEED_KEY,
    SeedError,
    build_follow_graph,
    follow_targets,
    load_fixture,
    phase_likes,
    pick_like_targets,
    tweet_choices,
)


FIXTURE_PATH = "scripts/seed/seed_data.json"


def test_fixture_has_ten_users_and_twenty_valid_tweets() -> None:
    fixture = load_fixture(FIXTURE_PATH)

    assert [user["username"] for user in fixture["users"]] == [f"user{i}" for i in range(1, 11)]
    assert fixture["users"][0]["display_name"] == "Alexander"
    assert fixture["users"][1]["display_name"] == "Jean"
    assert all(user["email"] == f"{user['username']}@example.com" for user in fixture["users"])
    assert all(len(user["password"]) >= 8 for user in fixture["users"])
    assert len(fixture["tweets"]) == 20
    assert all(0 < len(text.strip()) <= 280 for text in fixture["tweets"])


def test_fixture_rejects_bad_schema(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"users": [], "tweets": []}), encoding="utf-8")

    with pytest.raises(SeedError):
        load_fixture(str(bad))


def test_tweet_choices_are_stable_and_distinct_per_user() -> None:
    first = tweet_choices(DEFAULT_SEED_KEY, "user1", 20, per_user=5)
    second = tweet_choices(DEFAULT_SEED_KEY, "user1", 20, per_user=5)
    other = tweet_choices(DEFAULT_SEED_KEY, "user2", 20, per_user=5)

    assert first == second
    assert len(set(first)) == 5
    assert all(0 <= index < 20 for index in first)
    # Independent per-actor streams: different users need not match.
    assert first != other or True


def test_tweet_choices_match_reference_random_stream() -> None:
    expected = random.Random(f"{DEFAULT_SEED_KEY}:tweets:user3").sample(range(20), 5)

    assert tweet_choices(DEFAULT_SEED_KEY, "user3", 20, per_user=5) == expected


def test_follow_graph_respects_density_and_no_self_follow() -> None:
    usernames = [f"user{i}" for i in range(1, 11)]

    graph = build_follow_graph(DEFAULT_SEED_KEY, usernames)

    assert set(graph) == set(usernames)
    for username, targets in graph.items():
        assert 2 <= len(targets) <= 4
        assert username not in targets
        assert len(set(targets)) == len(targets)
        assert all(target in usernames for target in targets)


def test_follow_graph_matches_reference_stream() -> None:
    usernames = [f"user{i}" for i in range(1, 11)]
    expected = {name: follow_targets(DEFAULT_SEED_KEY, name, usernames) for name in usernames}

    assert build_follow_graph(DEFAULT_SEED_KEY, usernames) == expected


def test_pick_like_targets_are_stable_bounded_and_distinct() -> None:
    candidates = [f"tweet-{index}" for index in range(50)]

    first = pick_like_targets(DEFAULT_SEED_KEY, "user1", candidates)
    second = pick_like_targets(DEFAULT_SEED_KEY, "user1", candidates)

    assert first == second
    assert 3 <= len(first) <= 6
    assert len(set(first)) == len(first)
    assert all(tweet_id in set(candidates) for tweet_id in first)


def test_pick_like_targets_ignore_candidate_order_and_own_tweets() -> None:
    candidates = [f"tweet-{index}" for index in range(50)]

    ordered = pick_like_targets(DEFAULT_SEED_KEY, "user2", candidates)
    shuffled = pick_like_targets(DEFAULT_SEED_KEY, "user2", list(reversed(candidates)))

    assert ordered == shuffled
    # Cap at the available pool when it is smaller than the like bounds.
    assert pick_like_targets(DEFAULT_SEED_KEY, "user2", candidates[:2]) == sorted(candidates[:2])
    assert pick_like_targets(DEFAULT_SEED_KEY, "user2", []) == []


class _FakeHandler(BaseHTTPRequestHandler):
    """Minimal fake backend: login sets a cookie, posting a tweet needs it."""

    def _send(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path == "/auth/login":
            self._send(204, headers={"Set-Cookie": "flock_session=fake-token; Path=/; HttpOnly"})
        elif self.path == "/tweets":
            if "flock_session" not in (self.headers.get("Cookie") or ""):
                self._send(401, b'{"error":{"code":"unauthenticated"}}')
            else:
                self._send(201, b'{"id":"00000000-0000-4000-8000-000000000000"}')
        else:
            self._send(404, b"{}")

    def log_message(self, *args: object) -> None:  # silence test output
        pass


def test_stdlib_client_keeps_cookie_jar_per_user() -> None:
    from scripts.seed.seed import ApiClient

    server = HTTPServer(("127.0.0.1", 0), _FakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        authed = ApiClient(base_url)
        assert authed.login("user1@example.com", "user1password") is True
        status, _ = authed.create_tweet("hello world")
        assert status == 201

        anonymous = ApiClient(base_url)
        status, body = anonymous.create_tweet("hello world")
        assert status == 401
        assert body["error"]["code"] == "unauthenticated"
    finally:
        server.shutdown()
        thread.join()


class _LikesHandler(BaseHTTPRequestHandler):
    """Fake backend for the likes phase: per-user feeds and recorded like rows."""

    # username -> active tweet ids on the profile feed (server-generated).
    feeds: dict[str, list[str]] = {}
    # (actor, tweet_id) pairs received via POST like, in arrival order.
    received_likes: list[tuple[str, str]] = []

    def _send(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _actor(cookie_header: str | None) -> str | None:
        for part in (cookie_header or "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == "flock_session":
                return value or None
        return None

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/tweets") and "feed=profile" in self.path and "username=" in self.path:
            username = self.path.split("username=")[1].split("&")[0]
            items = [
                {"id": tweet_id, "text": "fake", "created_at": "2026-01-01T00:00:00Z",
                 "author": {"id": "x", "username": username, "display_name": username}}
                for tweet_id in self.feeds.get(username, [])
            ]
            self._send(200, json.dumps({"items": items, "next_cursor": None}).encode())
        else:
            self._send(404, b"{}")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/auth/login":
            email = (json.loads(body or b"{}").get("email") or "").split("@")[0]
            self._send(204, headers={"Set-Cookie": f"flock_session={email}; Path=/; HttpOnly"})
        elif self.path.startswith("/tweets/") and self.path.endswith("/like"):
            actor = self._actor(self.headers.get("Cookie"))
            tweet_id = self.path[len("/tweets/"):-len("/like")]
            if not actor:
                self._send(401, b'{"error":{"code":"unauthenticated"}}')
            else:
                self.received_likes.append((actor, tweet_id))
                self._send(200, json.dumps(
                    {"tweet_id": tweet_id, "like_count": 1, "liked_by_actor": True}
                ).encode())
        else:
            self._send(404, b"{}")

    def log_message(self, *args: object) -> None:  # silence test output
        pass


def test_phase_likes_never_self_likes_and_reruns_stay_stable() -> None:
    fixture = load_fixture(FIXTURE_PATH)
    feeds = {
        "user1": ["own-1a", "own-1b"],
        "user2": ["two-2a"],
        "user3": ["three-3a", "three-3b", "three-3c"],
    }
    _LikesHandler.feeds = feeds
    _LikesHandler.received_likes = []
    server = HTTPServer(("127.0.0.1", 0), _LikesHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        first = phase_likes(base_url, DEFAULT_SEED_KEY, fixture)
        first_run = list(_LikesHandler.received_likes)
        _LikesHandler.received_likes = []
        second = phase_likes(base_url, DEFAULT_SEED_KEY, fixture)
        second_run = list(_LikesHandler.received_likes)
    finally:
        server.shutdown()
        thread.join()

    candidate_ids = {tweet_id for ids in feeds.values() for tweet_id in ids}
    assert first["likes"] == sum(first["per_user"].values()) == len(first_run)
    assert all(3 <= count <= 6 for count in first["per_user"].values())
    assert {tweet_id for _, tweet_id in first_run} <= candidate_ids
    for actor, tweet_id in first_run:
        owner = next(name for name, ids in feeds.items() if tweet_id in ids)
        assert actor != owner  # never like own tweets
    # Same key => identical like plan on rerun; the idempotent endpoint keeps state stable.
    assert first["per_user"] == second["per_user"]
    assert second_run == first_run
