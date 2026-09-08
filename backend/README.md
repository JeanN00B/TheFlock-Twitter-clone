# Backend

FastAPI service for The Flock Twitter clone. Hexagonal layout under
`app/<capability>/` with `domain/`, `application/`, and `infrastructure/`.

## Prerequisites

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL 17 (Compose provides `twitter-db` and `twitter-testing-db`)

## Quick start (with Compose)

From the repo root (preferred):

```bash
cp ../.env.example ../.env   # if not already done
docker compose -f ../docker-compose.dev.yml up --build twitter-db twitter-backend
```

Health: http://localhost:8000/health

## Local (host) run

```bash
cd backend
uv sync
# Point DATABASE_URL at a reachable Postgres (Compose host port 5433 by default)
export DATABASE_URL=postgresql+psycopg://flock:flockpw@localhost:5433/flockdb
export APP_ENVIRONMENT=development
export NEXT_PUBLIC_APP_URL=http://localhost:3000
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Tests

```bash
docker compose -f ../docker-compose.dev.yml --profile test up -d twitter-testing-db
cd backend
uv sync
TEST_DATABASE_URL=postgresql+psycopg://flock:flockpw@localhost:5434/flockdb \
  uv run pytest --cov --cov-fail-under=80
```

Unit tests do not need Postgres; integration tests use `TEST_DATABASE_URL`.

## Seed

See [`scripts/seed/README.md`](scripts/seed/README.md). Docker profile:

```bash
docker compose -f ../docker-compose.dev.yml --profile seed run --rm twitter-seed
```

## Layout

| Path | Role |
|------|------|
| `app/users/` | Registration, public profiles, search, follows |
| `app/auth/` | Login, cookie sessions, `/auth/me`, logout |
| `app/tweets/` | Create / delete / feed / likes |
| `app/core/` | Settings |
| `app/composition.py` | FastAPI dependency wiring |
| `alembic/` | Migrations |
| `scripts/seed/` | Endpoint-first demo seeder |
| `tests/unit`, `tests/integration` | Pytest suite |

Dependency rule: `infrastructure → application → domain`. Domain stays
framework-free. Cross-capability imports may use another capability’s domain
values or application ports only — never its ORM/routers.
