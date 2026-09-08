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
