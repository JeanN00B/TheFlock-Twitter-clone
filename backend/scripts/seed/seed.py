"""Deterministic endpoint-first demo seeder (stdlib only, no app imports)."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_SEED_KEY = "flock-demo-v1"
FIXTURE_PATH = Path(__file__).with_name("seed_data.json")


class SeedError(Exception):
    """Fatal seeder failure with a human-readable message."""


# --- Fixture -----------------------------------------------------------------


def load_fixture(path: str | Path = FIXTURE_PATH) -> dict:
    """Load and validate the committed seed users and tweet texts."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SeedError(f"cannot read fixture {path}: {error}") from error

    users = raw.get("users")
    tweets = raw.get("tweets")
    if not isinstance(users, list) or len(users) != 10:
        raise SeedError("fixture must contain exactly 10 users")
    if not isinstance(tweets, list) or len(tweets) != 20:
        raise SeedError("fixture must contain exactly 20 tweet texts")

    expected_usernames = [f"user{i}" for i in range(1, 11)]
    for user, expected in zip(users, expected_usernames, strict=True):
        if (
            not isinstance(user, dict)
            or user.get("username") != expected
            or not isinstance(user.get("display_name"), str)
            or not user["display_name"].strip()
            or user.get("email") != f"{expected}@example.com"
            or not isinstance(user.get("password"), str)
            or not 8 <= len(user["password"]) <= 128
        ):
            raise SeedError(f"fixture user {expected!r} is invalid")
    for text in tweets:
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 280:
            raise SeedError("each fixture tweet must be 1..280 characters")

    return {"users": users, "tweets": tweets}


# --- Deterministic selection ---------------------------------------------------
# The seed key only controls *selection* (which templates, which follows).
# Server-generated tweet IDs and timestamps still differ per run, so reruns of
# the tweet phase create new rows; see the phase docstrings.


def tweet_choices(seed_key: str, username: str, template_count: int, per_user: int = 5) -> list[int]:
    """Return `per_user` distinct template indexes for one user (stable stream)."""
    rng = random.Random(f"{seed_key}:tweets:{username}")
    return rng.sample(range(template_count), per_user)


def follow_targets(seed_key: str, username: str, all_usernames: list[str]) -> list[str]:
    """Return 2..4 distinct non-self follow targets for one user (stable stream)."""
    rng = random.Random(f"{seed_key}:follows:{username}")
    candidates = [name for name in all_usernames if name != username]
    return rng.sample(candidates, rng.randint(2, 4))


def build_follow_graph(seed_key: str, usernames: list[str]) -> dict[str, list[str]]:
    """Build the runtime username-to-following-list map (outdegree 2..4, no self)."""
    return {name: follow_targets(seed_key, name, usernames) for name in usernames}


def pick_like_targets(
    seed_key: str, username: str, candidate_ids: list[str], min_likes: int = 3, max_likes: int = 6
) -> list[str]:
    """Pick 3..6 tweet IDs for one user to like (stable stream, idempotent).

    Candidates must already exclude the actor's own tweets. IDs are sorted
    before sampling so the choice is stable even though feed order varies
    with server timestamps. POST /like is set-state idempotent, so reruns
    converge instead of duplicating.
    """
    shortlist = sorted(set(candidate_ids))
    if not shortlist:
        return []
    rng = random.Random(f"{seed_key}:likes:{username}")
    count = min(rng.randint(min_likes, max_likes), len(shortlist))
    return sorted(rng.sample(shortlist, count))


# --- HTTP client (stdlib, one cookie jar per user) -----------------------------


class ApiClient:
    """Tiny JSON API client holding one user's session cookies."""

    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _request(
        self, method: str, path: str, body: dict | None = None
    ) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                payload = response.read().decode() or "{}"
                return response.status, json.loads(payload)
        except urllib.error.HTTPError as error:
            payload = error.read().decode() or "{}"
            try:
                return error.code, json.loads(payload)
            except json.JSONDecodeError:
                return error.code, {}

    def register(self, user: dict) -> tuple[int, dict]:
        return self._request("POST", "/auth/register", body=user)

    def login(self, email: str, password: str) -> bool:
        status, _ = self._request("POST", "/auth/login", {"email": email, "password": password})
        return status == 204

    def create_tweet(self, text: str) -> tuple[int, dict]:
        return self._request("POST", "/tweets", {"text": text})

    def follow(self, username: str) -> tuple[int, dict]:
        return self._request("POST", f"/users/{username}/follow")

    def profile_tweet_ids(self, username: str) -> list[str]:
        """List active tweet IDs for one profile, following pagination."""
        ids: list[str] = []
        cursor: str | None = None
        while True:
            path = f"/tweets?feed=profile&username={username}&page_size=50"
            if cursor is not None:
                path += f"&cursor={cursor}"
            status, body = self._request("GET", path)
            if status != 200:
                raise SeedError(f"cannot list tweets of {username} ({status} {body})")
            ids.extend(item["id"] for item in body.get("items", []))
            cursor = body.get("next_cursor")
            if not cursor:
                return ids

    def like_tweet(self, tweet_id: str) -> tuple[int, dict]:
        return self._request("POST", f"/tweets/{tweet_id}/like")

    def logout(self) -> None:
        try:
            self._request("POST", "/auth/logout")
        except Exception:  # noqa: BLE001 - cleanup must not fail the seed
            pass


# --- Phases --------------------------------------------------------------------


def _login_all(base_url: str, users: list[dict]) -> dict[str, ApiClient]:
    """Log every seed user in; each phase authenticates before attempting writes."""
    sessions: dict[str, ApiClient] = {}
    for user in users:
        client = ApiClient(base_url)
        if not client.login(user["email"], user["password"]):
            raise SeedError(f"cannot log in {user['username']}; run `seed users` first")
        sessions[user["username"]] = client
    return sessions


def _logout_all(sessions: dict[str, ApiClient]) -> None:
    for client in sessions.values():
        client.logout()


def phase_users(base_url: str, fixture: dict) -> dict[str, int]:
    """Register missing users; fail closed on conflicting existing credentials.

    Preflight is an API-only heuristic: try the expected login first (already
    seeded), else register. A 409 whose credentials do not match the fixture
    means someone else owns that handle/email, so abort and ask for a clean
    dev database. Earlier users created by this run are intentionally left in
    place rather than deleted through a privileged API.
    """
    created = existing = 0
    for user in fixture["users"]:
        probe = ApiClient(base_url)
        if probe.login(user["email"], user["password"]):
            existing += 1
            print(f"  {user['username']}: already seeded")
            continue
        status, body = probe.register(user)
        if status == 201:
            created += 1
            print(f"  {user['username']}: registered")
        elif status == 409:
            if probe.login(user["email"], user["password"]):
                existing += 1
                print(f"  {user['username']}: already seeded")
            else:
                raise SeedError(
                    f"{user['username']}: handle/email exists with different credentials; "
                    "use a clean dev database"
                )
        else:
            raise SeedError(f"{user['username']}: register failed ({status} {body})")
    return {"created": created, "existing": existing}


def phase_tweets(base_url: str, seed_key: str, fixture: dict) -> dict[str, int]:
    """Post 5 distinct template tweets per user (50 total).

    Intentionally one-shot and non-idempotent: POST /tweets mints a new ID and
    timestamp per call, so reruns post 50 more tweets. The stable key only
    reproduces the *selection*, never the rows.
    """
    sessions = _login_all(base_url, fixture["users"])
    try:
        posted = 0
        per_user: dict[str, int] = {}
        for user in fixture["users"]:
            client = sessions[user["username"]]
            indexes = tweet_choices(seed_key, user["username"], len(fixture["tweets"]))
            for index in indexes:
                status, body = client.create_tweet(fixture["tweets"][index])
                if status != 201:
                    raise SeedError(f"{user['username']}: tweet post failed ({status} {body})")
                posted += 1
            per_user[user["username"]] = len(indexes)
            print(f"  {user['username']}: posted {len(indexes)} tweets")
        return {"posted": posted, "per_user": per_user}
    finally:
        _logout_all(sessions)


def phase_follows(base_url: str, seed_key: str, fixture: dict) -> dict:
    """Apply the runtime-generated follow graph (endpoint is idempotent)."""
    usernames = [user["username"] for user in fixture["users"]]
    graph = build_follow_graph(seed_key, usernames)
    sessions = _login_all(base_url, fixture["users"])
    try:
        edges = 0
        for username, targets in graph.items():
            client = sessions[username]
            for target in targets:
                status, body = client.follow(target)
                if status != 200:
                    raise SeedError(f"{username} -> {target}: follow failed ({status} {body})")
                edges += 1
            print(f"  {username}: follows {len(targets)} users")
        return {"edges": edges, "graph": graph}
    finally:
        _logout_all(sessions)


def phase_likes(base_url: str, seed_key: str, fixture: dict) -> dict:
    """Like 3..6 tweets per user, authored only by the other nine users.

    Tweet IDs are discovered through the profile feed (server-generated, so
    they cannot be derived from the seed key). Reruns are safe: the like
    endpoint applies idempotent set-state and repeats converge.
    """
    sessions = _login_all(base_url, fixture["users"])
    try:
        by_author: dict[str, list[str]] = {}
        for user in fixture["users"]:
            by_author[user["username"]] = sessions[user["username"]].profile_tweet_ids(
                user["username"]
            )
        total = 0
        per_user: dict[str, int] = {}
        for user in fixture["users"]:
            username = user["username"]
            candidates = [
                tweet_id
                for author, ids in by_author.items()
                if author != username
                for tweet_id in ids
            ]
            targets = pick_like_targets(seed_key, username, candidates)
            client = sessions[username]
            for tweet_id in targets:
                status, body = client.like_tweet(tweet_id)
                if status != 200:
                    raise SeedError(f"{username}: like failed ({status} {body})")
                total += 1
            per_user[username] = len(targets)
            print(f"  {username}: liked {len(targets)} tweets")
        return {"likes": total, "per_user": per_user}
    finally:
        _logout_all(sessions)


PHASES = ("users", "tweets", "follows", "likes", "all")


def run_phase(phase: str, base_url: str, seed_key: str, fixture: dict) -> dict:
    if phase == "users":
        return phase_users(base_url, fixture)
    if phase == "tweets":
        return phase_tweets(base_url, seed_key, fixture)
    if phase == "follows":
        return phase_follows(base_url, seed_key, fixture)
    if phase == "likes":
        return phase_likes(base_url, seed_key, fixture)
    if phase == "all":
        users = run_phase("users", base_url, seed_key, fixture)
        tweets = run_phase("tweets", base_url, seed_key, fixture)
        follows = run_phase("follows", base_url, seed_key, fixture)
        likes = run_phase("likes", base_url, seed_key, fixture)
        return {"users": users, "tweets": tweets, "follows": follows, "likes": likes}
    raise SeedError(f"unknown phase {phase!r}; choose from {', '.join(PHASES)}")


def print_summary(phase: str, result: dict, usernames: list[str]) -> None:
    if phase == "all":
        graph = result["follows"]["graph"]
        tweets = result["tweets"]["per_user"]
        likes = result["likes"]["per_user"]
    elif phase == "follows":
        graph, tweets, likes = result["graph"], {}, {}
    elif phase == "likes":
        graph, tweets, likes = {}, {}, result["per_user"]
    else:
        graph, tweets, likes = {}, result.get("per_user", {}), {}
    followers: dict[str, int] = {name: 0 for name in usernames}
    for targets in graph.values():
        for target in targets:
            followers[target] += 1
    if graph or tweets or likes:
        print("\nusername   tweets  following  followers  likes")
        for name in usernames:
            print(
                f"{name:<10} {tweets.get(name, '-'):>6}  "
                f"{len(graph.get(name, [])) if graph else '-':>9}  "
                f"{followers.get(name, '-') if graph else '-':>9}  "
                f"{likes.get(name, '-') if likes else '-':>5}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed theFlock-twitter demo data via HTTP.")
    parser.add_argument("phase", choices=PHASES, help="seed phase to run")
    parser.add_argument("--base-url", default="http://localhost:8000", help="backend base URL")
    parser.add_argument("--seed", default=DEFAULT_SEED_KEY, help="deterministic selection key")
    parser.add_argument("--fixture", default=str(FIXTURE_PATH), help="path to seed_data.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        fixture = load_fixture(args.fixture)
        print(f"seeding phase `{args.phase}` against {args.base_url} (key={args.seed})")
        result = run_phase(args.phase, args.base_url.rstrip("/"), args.seed, fixture)
        print_summary(args.phase, result, [u["username"] for u in fixture["users"]])
    except SeedError as error:
        print(f"seed failed: {error}", file=sys.stderr)
        return 1
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
