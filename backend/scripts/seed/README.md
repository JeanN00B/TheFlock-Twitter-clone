# Demo seeder

Endpoint-first deterministic seed: 10 users, 50 tweets, runtime-generated follow graph. Likes are deferred as a separate follow-up.

## Default invocation (Docker, recommended)

```bash
docker compose -f docker-compose.dev.yml --profile seed run --rm twitter-seed
```

## Local alternative

```bash
cd backend
uv run python -m scripts.seed all --base-url http://localhost:8000
```

## Phases

```bash
uv run python -m scripts.seed users --base-url http://localhost:8000
uv run python -m scripts.seed tweets --base-url http://localhost:8000
uv run python -m scripts.seed follows --base-url http://localhost:8000
uv run python -m scripts.seed all --base-url http://localhost:8000 [--seed KEY]
```

Default selection key is `flock-demo-v1`; override with `--seed KEY` for an alternate deterministic dataset.

## Replay policy

- `users`: API-only heuristic. Tries the expected login first, else registers. Fails closed if a handle/email exists with different credentials — use a clean dev database.
- `tweets`: intentionally one-shot. Each run posts 5 tweets per user (50 total) because `POST /tweets` mints a new ID/timestamp. The stable key reproduces the *selection*, never the rows.
- `follows`: safe to rerun; the follow endpoint is idempotent.
- `all`: runs users → tweets → follows, then reports that likes are deferred.

All sessions are logged out at the end of each phase. HTTP uses the Python standard library only; sessions are one cookie jar per user.
