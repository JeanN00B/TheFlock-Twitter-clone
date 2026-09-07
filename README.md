# The Flock - Twitter clone

Run the full stack with Docker — no local Postgres or Node needed.

## Details
#### Stack
- Nextsj: Client with SSR, CSR, it will just consume the backend endpoints
- FastAPI: Excelent for a fast prototyping
- Postgres SQL: Relational DB
- Docker Engine + Compose v2. Verify:
  ```bash
  docker --version
  docker compose version
  ```

| Service | Container | Host URL |
|---------|-----------|----------|
| `twitter-frontend` | Next.js (prod build) | `http://localhost:3000` |
| `twitter-backend` | FastAPI | `http://localhost:8000/health` |
| `twitter-db` | Postgres 17 | `localhost:5433` |

## Quickstart

1. Clone and enter the repo:
   ```bash
   git clone <repo-url> && cd theFlock-twitter
   ```
2. Copy env (edit defaults if needed):
   ```bash
   cp .env.example .env
   ```
   This copies `POSTGRES_USER`, `POSTGRES_PASSWORD=<REDACTED>`, `POSTGRES_DB`, `DATABASE_URL` (with `<REDACTED>` password), `TWITTER_DB_PORT`, `TWITTER_BACKEND_PORT`, `TWITTER_FRONTEND_PORT`, `BACKEND_API_URL`, `BACKEND_SECRET_KEY=<REDACTED>`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_APP_URL`, `APP_ENVIRONMENT`, `NODE_ENV`, `TEST_DATABASE_URL`, and `AUTO_MIGRATE`
3. Run:
   ```bash
   # Production version
   docker compose up --build

   # Development version (recommended to start)
   docker compose -f docker-compose.dev.yml up --build

   # Start development with testing DB
   docker compose -f docker-compose.dev.yml --profile test up --build
   ```
  Note: `docker-compose.dev.yml` uses top-level `include` to pull `docker-compose.yml`, so the single `-f` form above is standalone. The old merged `-f docker-compose.yml -f docker-compose.dev.yml` form still parses but is now redundant.


4. Open frontend `http://localhost:3000` and backend health `http://localhost:8000/health`.


## Disposable PostgreSQL test runbook

Start only the isolated test database from the development Compose file:

```bash
docker compose -f docker-compose.dev.yml --profile test up
cd backend

uv run pytest
```


