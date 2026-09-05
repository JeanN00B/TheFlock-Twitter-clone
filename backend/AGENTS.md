# Backend — FastAPI (hexagonal, flat `app/`)

## Boundaries
- `app/domain/` — entities + business rules. No FastAPI/SQLAlchemy imports.
- `app/application/` — use cases orchestrating domain ports; framework-free.
- `app/infrastructure/` — adapters: SQLAlchemy models, repositories, FastAPI routers.
- `app/core/` — settings, logging, shared config.
- Dependency rule: inward only (`infrastructure → application → domain`);
  domain never imports outward.

## Tooling (uv only — no pip)
- `uv sync` / `uv run ...`; locked with `uv.lock` (`--frozen` in Docker).
- DB: sync SQLAlchemy + psycopg (`postgresql+psycopg://...`), single alembic
  env (`alembic upgrade head` in entrypoint when `alembic.ini` exists).
- Tests: `pytest` with `pytest-cov --fail-under=80` (challenge minimum).

## Contracts
- `GET /health` → `{"status": "ok"}` (Docker HEALTHCHECK + compose gating).
- Routers live in `infrastructure/`; keep I/O at the edges.
