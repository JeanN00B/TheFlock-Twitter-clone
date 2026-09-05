# theFlock-twitter — Monorepo Rules

Twitter/X clone (The Flock challenge): `frontend/` (Next.js, client-only) +
`backend/` (FastAPI, hexagonal flat `app/`) + Postgres 17.

## Layout
- `frontend/` — client-only; consumes the backend over HTTP, no direct DB access.
- `backend/app/` — hexagonal, flat: `domain/` (entities, no framework),
  `application/` (use cases), `infrastructure/` (SQLAlchemy, routers),
  `core/` (settings).
- `docker-compose.yml` dev / `docker-compose.prod.yml` prod override.

## Commands
- Frontend (pnpm only): `pnpm dev` (Turbopack) · `pnpm build` · `pnpm lint`
- Backend (uv only, no pip): `uv sync` · `uv run uvicorn app.main:app --reload` ·
  `uv run pytest --cov --cov-fail-under=80`
- Stack: `docker compose up --build` (dev) · prod adds `-f docker-compose.prod.yml`

## Git
Conventional commits, no squash (history is graded), no AI attribution trailers.

See README Runbook for setup/seed and CONTEXT.md (frozen challenge spec).
