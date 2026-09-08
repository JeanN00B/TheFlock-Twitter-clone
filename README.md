# The Flock — Twitter/X clone

Full-stack Twitter/X clone for The Flock challenge: cookie-session auth, tweets,
follows, likes, user search, and Docker Compose for one-command bring-up.


| Layer    | Choice                                                                 |
| -------- | ---------------------------------------------------------------------- |
| Frontend | Next.js 16 (App Router, client-only) + React 19 + Tailwind v4 + shadcn |
| Backend  | FastAPI (hexagonal, capability-first) + SQLAlchemy + Alembic           |
| Database | PostgreSQL 17                                                          |
| Tooling  | pnpm 10.32.1 · uv · Docker Compose v2                                  |


---



## Runbook (Setup & Operations)



### Prerequisites

Exact versions used by this repo:


| Tool                       | Version                                                                                       |
| -------------------------- | --------------------------------------------------------------------------------------------- |
| Docker Engine + Compose v2 | Docker 25+ (Compose V2 plugin)                                                                |
| Node.js                    | 24 (matches frontend Docker images)                                                           |
| pnpm                       | 10.32.1 via Corepack                                                                          |
| Python                     | 3.12+ (Docker images use 3.12; `requires-python >=3.12`)                                      |
| uv                         | latest stable (`curl -LsSf [https://astral.sh/uv/install.sh](https://astral.sh/uv/install.sh) |


Verify:

```bash
docker --version
docker compose version
node --version    # optional for host frontend
corepack enable && corepack prepare pnpm@10.32.1 --activate
uv --version      # optional for host backend / tests
```



### Installation

```bash
git clone <repo-url> && cd theFlock-twitter
cp .env.example .env
```

Edit `.env` only if ports or secrets conflict on your machine. Defaults are enough
for local evaluation.

### Start (development — recommended)

```bash
docker compose -f docker-compose.dev.yml up --build
# you can run seeding as well
docker compose -f docker-compose.dev.yml --profile seed up --build
# or run seed locally after setting up the backend see [seed README](backend/scripts/seed/README.md)
```


| Service         | URL                                                          |
| --------------- | ------------------------------------------------------------ |
| Frontend        | [http://localhost:3000](http://localhost:3000)               |
| Backend health  | [http://localhost:8000/health](http://localhost:8000/health) |
| Postgres (host) | `localhost:5433`                                             |


`docker-compose.dev.yml` includes the base compose file, so a single `-f` is enough.

### Start (production-style images)

```bash
docker compose up --build
```

Same host ports by default (`3000` / `8000` / `5433` via `.env`).

### Seed demo data

With the stack already running:

```bash
docker compose -f docker-compose.dev.yml --profile seed run --rm twitter-seed
```

Creates **10 users**, **50 tweets**, a deterministic follow graph, and **3–6
cross-likes per user**. Details: `[backend/scripts/seed/README.md](backend/scripts/seed/README.md)`.

**Sample login (after seed):**


| Field    | Value               |
| -------- | ------------------- |
| Email    | `user1@example.com` |
| Password | `user1password`     |
| Username | `user1`             |


Same pattern for `user2`…`user10` (`userN@example.com` / `userNpassword`).

Host alternative (backend already reachable):

```bash
cd backend
uv sync
uv run python -m scripts.seed all --base-url http://localhost:8000
```



### Run the full test suite

**Backend** (needs the disposable test Postgres):

```bash
docker compose -f docker-compose.dev.yml --profile test up -d twitter-testing-db
cd backend
uv sync
TEST_DATABASE_URL=postgresql+psycopg://flock:flockpw@localhost:5434/flockdb \
  uv run pytest --cov --cov-fail-under=80
```

**Frontend** (Vitest + MSW; no live backend):

```bash
cd frontend
corepack enable && corepack prepare pnpm@10.32.1 --activate
pnpm install
pnpm test
```



### Environment variables

Copy from `[.env.example](.env.example)`. Summary:


| Variable                                              | Purpose                                               | Example                                                      |
| ----------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------ |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Postgres credentials                                  | `flock` / `flockpw` / `flockdb`                              |
| `DATABASE_URL`                                        | Backend SQLAlchemy URL (in-compose host `twitter-db`) | `postgresql+psycopg://flock:flockpw@twitter-db:5432/flockdb` |
| `TWITTER_DB_PORT`                                     | Host port for Postgres                                | `5433`                                                       |
| `TWITTER_BACKEND_PORT`                                | Host port for API                                     | `8000`                                                       |
| `TWITTER_FRONTEND_PORT`                               | Host port for UI                                      | `3000`                                                       |
| `BACKEND_API_URL`                                     | Server-side backend URL inside Docker                 | `http://twitter-backend:8000`                                |
| `BACKEND_SECRET_KEY`                                  | Backend secret material                               | `your_secret_key`                                            |
| `NEXT_PUBLIC_API_URL`                                 | Browser → backend URL (baked at frontend build)       | `http://localhost:8000`                                      |
| `NEXT_PUBLIC_APP_URL`                                 | Browser app origin; CORS / cookie origin allowlist    | `http://localhost:3000`                                      |
| `APP_ENVIRONMENT`                                     | Controls session cookie `Secure` flag                 | `development`                                                |
| `NODE_ENV`                                            | Node environment for frontend containers              | `production` / `development`                                 |
| `AUTO_MIGRATE`                                        | Run `alembic upgrade head` on backend start           | `true` in dev overlay                                        |
| `TEST_DATABASE_URL`                                   | Pytest integration DB (host port **5434**)            | `postgresql+psycopg://flock:flockpw@localhost:5434/flockdb`  |


---



## What works today

- **Auth:** register, login, logout, cookie session (`flock_session`), protected API routes, shell gated on session
- **Tweets:** create (≤280), delete own, cursor pagination / infinite scroll
- **Feeds:** Home = global (`feed=all`); Feed = following (`feed=following`); profile timelines
- **Social:** follow / unfollow, like / unlike with visible counts, profile follower/following **counts**, user search
- **Responsive:** Tailwind mobile-first shell (sidebar → sheet on small viewports)
- **Bonus:** full-stack Docker Compose (dev + prod-style)

---



## Technical decisions



### Why this stack

- **FastAPI + Postgres** for a reliable and fast development, typed HTTP APIs, migrations, and relational modeling of users, follows, tweets, and likes, swagger by default is very useful to provide a live endpoint for frontend agent, and the front contract wont drift from the backend so easy.
- **Hexagonal / capability-first backend** (`app/<capability>/{domain,application,infrastructure}`) so domain rules stay framework-free and tests can target use cases without the web stack, easyer for testing.
- **Next.js client-only frontend** talking only over HTTP through a single `BackendGateway` — no shared DB, no server-side data coupling. Matches the challenge’s “frontend consumes the backend” shape and keeps auth as browser cookies with `credentials: include`. The initial reason to choos Nextjs is due to SSR and SSE,  but those capabilities where not fully used due to time.
- **uv / pnpm / Compose** for reproducible installs and a Runbook that works without local Postgres.



### Timeline and follows graph

- Follows are rows in `follow_relationships` (follower → followee), idempotent POST/DELETE.
- Tweet feeds are **read-time joins**, not a fan-out write path:
  - `feed=all` — active tweets, newest first
  - `feed=following` — active tweets whose author is in the actor’s following set (excludes the actor’s own tweets)
  - `feed=profile&username=` — that user’s active tweets
- Pagination uses opaque, **scope-bound v2 cursors** (`created_at` + tweet id). A cursor from one feed cannot be reused on another.



### Authentication

- Custom auth (no Firebase / Supabase Auth).
- Registration: `POST /auth/register` (no session).
- Login: `POST /auth/login` verifies Argon2 hashes, persists a **digest-only** session row, sets httpOnly `flock_session` (7-day absolute lifetime).
- Protected routes resolve the cookie → digest → user; logout revokes the digest and clears the cookie.
- Browser origin is constrained via `NEXT_PUBLIC_APP_URL` for credentialed CORS.



### Known trade-offs and limitations

- **Bio:** not persisted yet. Profiles show display name, `@username`, and an initials avatar placeholder.
- **Followers / following lists:** backend list endpoints exist (`GET /users/{username}/followers|following`); the UI currently shows **counts only**, not browsable lists.
- **E2E:** backend has unit + integration coverage (≥80% gate); frontend has Vitest/MSW integration-style tests. There is not yet a browser e2e harness (Playwright/Cypress) for the auth flow.
- **Realtime / media / threads / notifications:** not implemented; Docker Compose is the chosen bonus.
- Home is a global discovery feed; the challenge “timeline of followed users” is the dedicated **Feed** route (`/feed`).



### AI tools used

Development used **Cursor** (agentic coding) with structured SDD-style planning for backend slices (auth, feeds, likes, seed) and frontend feature slices (session, feeds, social, search). Humans directed scope, reviewed contracts, and kept commit history progressive rather than squashed.

---



## Repo map

```
frontend/   Next.js client (pnpm)
backend/    FastAPI app + Alembic + seed scripts (uv)
docker-compose.yml          base / prod-style stack
docker-compose.dev.yml      reload mounts, seed + test profiles
.env.example                required env template
CONTEXT.md                  frozen challenge brief (do not treat as editable product docs)
```

Package-level notes: `[frontend/README.md](frontend/README.md)`, `[backend/README.md](backend/README.md)`.